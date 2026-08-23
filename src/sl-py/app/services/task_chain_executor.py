"""
TaskChainExecutor - v0_1_2: 任务链执行 + 中断检查 + 可靠性修复
链式循环：选模型→strata-match→工具循环→verify→下一步
集成 strata-match sg- Job 交互 + 失败处理。
"""

import json
import logging
import time
from typing import Any, Optional
from uuid import uuid4

import aiosqlite

from .internal_reasoner import InternalReasoner
from .context_injector import ContextInjector

logger = logging.getLogger(__name__)


class TaskCancelledError(Exception):
    """v0_1_1: 任务被取消异常"""
    def __init__(self, chain_id: str):
        self.chain_id = chain_id
        super().__init__(f"Task chain cancelled: {chain_id}")


class StepExecutionError(Exception):
    """v0_1_2: 步骤执行异常——不再被吞"""
    def __init__(self, step_name: str, original_error: Exception):
        self.step_name = step_name
        self.original_error = original_error
        super().__init__(f"Step '{step_name}' failed: {original_error}")


class TaskChainExecutor:
    """任务链执行器"""

    def __init__(self):
        self.reasoner = InternalReasoner()
        self.injector = ContextInjector()

    async def _check_cancelled(self, session) -> None:
        """v0_1_2: 中断检查——使用全局共享 DB 连接"""
        chain_id = getattr(session, 'active_chain_id', None)
        if not chain_id:
            return
        try:
            from ..database import get_shared_db
            db = await get_shared_db()
            cursor = await db.execute(
                "SELECT status FROM tasks WHERE session_id = ? AND status = 'cancelled' LIMIT 1",
                (session.session_id,),
            )
            row = await cursor.fetchone()
            if row:
                raise TaskCancelledError(chain_id)
        except TaskCancelledError:
            raise
        except Exception:
            pass  # DB 查询失败不影响正常流程

    async def execute(
        self,
        user_ask: str,
        session,
        downstream_llm,
        context_router,
        tool_dispatcher,
        strata_match_client,
        model_selector,
        logic_category: str = "",
        api_key: str = "",
        max_tokens: int = 4096,
    ) -> dict:
        """
        执行 task_chain 全流程：计划→执行→验证→汇总 (v0_1_1: 带中断检查)

        Returns:
            {
                "chain_id": "sg-xxx",
                "steps": [...],
                "summary": "...",
                "failed": False/True,
                "pending_steps": [...]
            }
        """
        chain_id = f"sg-{session.session_id}-{int(time.time())}"
        session.set_active_chain(chain_id)
        logger.info(f"TaskChain started: {chain_id}, user_ask={user_ask[:50]}")

        try:
            # 1. 计划
            endpoint_name, model = model_selector.select("task_chain", logic_category)
            steps = await self.reasoner.plan(user_ask, downstream_llm, model=model, api_key=api_key)
            if not steps:
                steps = ["执行用户请求"]

            results = []
            failed = False
            failed_at = None

            # 2. 逐步骤执行
            for i, step_name in enumerate(steps):
                step_num = i + 1

                # v0_1_1: 中断检查
                await self._check_cancelled(session)

                # 注入上下文
                ctx = self.injector.inject(step_num, step_name, results)

                # 调 strata-match（带 job_id + step）
                try:
                    sp_result = await strata_match_client.query(
                        user_ask=f"{ctx}\n{step_name}",
                        subtypes=logic_category,
                    )
                    sp_result["_chain_id"] = chain_id
                    sp_result["_step"] = step_num
                except Exception as e:
                    logger.error(f"strata-match query failed at step {step_num}: {e}")
                    sp_result = {"primary_prompt": "", "matched_skills_tags": []}

                # 执行工具循环 (v0_1_2: 捕获 StepExecutionError 标记失败)
                full_prompt = sp_result.get("primary_prompt", session.permanent_system_prompt)
                try:
                    step_result_text = await self._execute_step(
                        ctx, step_name, full_prompt, downstream_llm, context_router,
                        tool_dispatcher, session, model, api_key, endpoint_name, max_tokens
                    )
                except StepExecutionError as e:
                    logger.error(f"Step execution failed at step {step_num} '{step_name}': {e.original_error}")
                    step_result_text = f"StepExecutionError: {e.original_error}"

                # 3. 验证 (v0_1_2: 默认 passed=False，异常不再被吞)
                verification = {"passed": False, "feedback": "verification_unavailable"}
                try:
                    verification = await self.reasoner.verify(step_result_text, step_name, downstream_llm, model=model, api_key=api_key)
                except Exception as e:
                    logger.error(f"Verification error at step {step_name}: {e}")
                    verification = {"passed": False, "feedback": f"verification_error: {str(e)}"}

                step_record = {
                    "step_num": step_num,
                    "step_name": step_name,
                    "status": "completed" if verification.get("passed", True) else "failed",
                    "summary": step_result_text[:300],
                    "verification": verification.get("feedback", ""),
                }
                results.append(step_record)

                if not verification.get("passed", True):
                    failed = True
                    failed_at = step_num
                    logger.warning(f"Step {step_num} failed: {verification.get('feedback', '')}")
                    break

            # 4. 汇总
            summary = ""
            if not failed:
                completed = [r for r in results if r["status"] == "completed"]
                summary = await self.reasoner.summarize(completed, downstream_llm, model=model, api_key=api_key)

            pending = steps[failed_at:] if failed else []

            return {
                "chain_id": chain_id,
                "steps": results,
                "summary": summary,
                "failed": failed,
                "failed_at_step": failed_at,
                "pending_steps": pending,
            }

        except TaskCancelledError as e:
            logger.warning(f"TaskChain cancelled at runtime: {chain_id}")
            return {
                "chain_id": chain_id,
                "steps": [],
                "summary": f"Task cancelled: {chain_id}",
                "failed": True,
                "failed_at_step": 0,
                "pending_steps": [],
                "cancelled": True,
            }

        finally:
            session.set_active_chain(None)

    async def _execute_step(
        self, ctx: str, step_name: str, system_prompt: str,
        downstream_llm, context_router, tool_dispatcher, session,
        model: str, api_key: str, endpoint_name: str = "", max_tokens: int = 4096
    ) -> str:
        """执行单步骤的工具调用循环"""
        messages = [
            {"role": "system", "content": f"{system_prompt}\n\n{ctx}"},
            {"role": "user", "content": step_name},
        ]
        tools = tool_dispatcher.definitions if tool_dispatcher.definitions else None

        try:
            response = await downstream_llm.chat(
                messages=messages, model=model, tools=tools, api_key=api_key,
                endpoint_name=endpoint_name, max_tokens=max_tokens,
            )
            content = response.get("choices", [{}])[0].get("message", {}).get("content", "")
            return content or f"完成{step_name}"
        except Exception as e:
            logger.error(f"Step execution failed: {step_name}, {e}")
            raise StepExecutionError(step_name=step_name, original_error=e)
