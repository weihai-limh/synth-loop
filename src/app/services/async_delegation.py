"""异步委托 text-cli (v0_1_2 T8)

委托/轮询 text-cli task_manager——不补 worker
数据流：T6 编译 plan → 每相位 POST text-cli --async → task_id → 轮询 → done/error → 相位推进
"""

import asyncio
import json
import logging
from typing import Any, Optional

import httpx

from ..models.pipeline import PipelineSession, PhaseDefinition, PhaseStatus
from .phase_executor import PhaseExecutor

logger = logging.getLogger(__name__)


class TextCLITaskError(Exception):
    """text-cli 任务执行异常"""
    def __init__(self, task_id: str, detail: Any = None):
        self.task_id = task_id
        self.detail = detail
        super().__init__(f"TextCLI task {task_id} failed: {detail}")


class AsyncDelegationService:
    """异步委托服务——委托 text-cli 执行相位任务"""

    def __init__(self, textcli_url: str = "http://localhost:28050"):
        self.textcli_url = textcli_url
        self.phase_executor = PhaseExecutor()

    # ═══════════════════════════════════════════════════════════
    # 委托调用
    # ═══════════════════════════════════════════════════════════

    async def delegate_to_textcli(self, step_name: str, path_json: dict) -> str:
        """调 text-cli --async → 返回 task_id

        Args:
            step_name: 当前相位名称（用于 prompt）
            path_json: T6 编译产出的 path JSON
        Returns:
            text-cli task_manager 返回的 task_id
        """
        prompt = f"AI:text-cli;path,{json.dumps(path_json, ensure_ascii=False)},--async"
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    f"{self.textcli_url}/text-cli/cli",
                    json={"prompt": prompt},
                )
                resp.raise_for_status()
                data = resp.json()

                # 解析 text-cli 响应格式: rst_data.text 内含 JSON
                rst_text = data.get("rst_data", {}).get("text", "{}")
                task_info = json.loads(rst_text) if isinstance(rst_text, str) else rst_text
                task_id = task_info.get("task_id", task_info.get("id"))
                logger.info(f"Delegated to text-cli: {step_name} → task_id={task_id}")
                return task_id
        except Exception as e:
            logger.error(f"Delegate to text-cli failed: {e}")
            raise

    # ═══════════════════════════════════════════════════════════
    # 轮询状态
    # ═══════════════════════════════════════════════════════════

    async def poll_textcli_task(self, task_id: str, poll_interval: int = 2,
                                 max_wait: int = 300) -> dict:
        """轮询 text-cli 任务状态——最大等待 300s

        Returns:
            {"status": "done", "result": {...}}
        Raises:
            TextCLITaskError: text-cli 返回 error
            TimeoutError: 超时
        """
        elapsed = 0
        while elapsed < max_wait:
            try:
                async with httpx.AsyncClient(timeout=10) as client:
                    resp = await client.get(
                        f"{self.textcli_url}/text-cli/tasks/{task_id}",
                    )
                    resp.raise_for_status()
                    data = resp.json()

                    status = data.get("task", {}).get("state", "")
                    if status == "done":
                        logger.info(f"TextCLI task {task_id}: done")
                        return data
                    if status == "error":
                        detail = data.get("result", data.get("error", "unknown error"))
                        logger.error(f"TextCLI task {task_id}: error — {detail}")
                        raise TextCLITaskError(task_id=task_id, detail=detail)

                    logger.debug(f"TextCLI task {task_id}: {status} (elapsed={elapsed}s)")
            except TextCLITaskError:
                raise
            except Exception as e:
                logger.warning(f"Poll failed for {task_id}: {e} (retrying)")

            await asyncio.sleep(poll_interval)
            elapsed += poll_interval

        raise TimeoutError(f"TextCLI task {task_id} timed out after {max_wait}s")

    # ═══════════════════════════════════════════════════════════
    # 相位异步执行（T5 注入 + T6 编译 → T8 委托 → 轮询 → 推进）
    # ═══════════════════════════════════════════════════════════

    async def execute_phase(self, pipeline: PipelineSession,
                             phase: PhaseDefinition,
                             path_json: dict) -> str:
        """执行单个相位：委托 text-cli → 轮询 → 返回结果

        Args:
            pipeline: 管道会话
            phase: 当前相位定义
            path_json: T6 编译产物
        Returns:
            相位执行结果文本
        Raises:
            TextCLITaskError / TimeoutError / Exception → 调用方负责 quality_gate
        """
        # 委托 text-cli
        task_id = await self.delegate_to_textcli(phase.name, path_json)

        # 记录 AsyncTask
        from ..models.pipeline import AsyncTask
        async_task = AsyncTask(
            task_id=f"synth-{task_id}",
            phase_index=phase.index,
            status="running",
            text_cli_task_id=task_id,
        )
        pipeline.async_tasks.append(async_task)

        logger.info(f"Phase {phase.index} ({phase.name}): delegated, text_cli_task_id={task_id}")

        # 轮询直到完成
        result_data = await self.poll_textcli_task(task_id)

        # 提取输出
        output = ""
        if isinstance(result_data.get("result"), dict):
            output = result_data["result"].get("output", json.dumps(result_data["result"]))
        elif isinstance(result_data.get("result"), str):
            output = result_data["result"]
        else:
            output = json.dumps(result_data)

        # 更新 AsyncTask 状态
        async_task.status = "done"

        logger.info(f"Phase {phase.index} ({phase.name}): completed via text-cli")
        return output

    # ═══════════════════════════════════════════════════════════
    # 管道级编排：按顺序执行所有相位
    # ═══════════════════════════════════════════════════════════

    async def run_pipeline(self, pipeline: PipelineSession,
                            path_jsons: list[dict]) -> PipelineSession:
        """按相位顺序委托 text-cli 执行整条管道

        Args:
            pipeline: 已启动的管道会话
            path_jsons: T6 编译产出的 path JSON 列表（按相位顺序）
        Returns:
            更新后的 PipelineSession
        """
        for i, phase in enumerate(pipeline.phases):
            if phase.status in {PhaseStatus.COMPLETED, PhaseStatus.FAILED}:
                continue

            phase.status = PhaseStatus.RUNNING
            pipeline.updated_at = None  # 触发更新

            try:
                path_json = path_jsons[i] if i < len(path_jsons) else {}
                output = await self.execute_phase(pipeline, phase, path_json)

                # quality_gate 评估
                status = await self.phase_executor.evaluate_quality_gate(
                    pipeline, phase.index, execution_passed=True,
                    detail=f"text-cli task completed",
                )

                if status == PhaseStatus.AWAITING_APPROVAL:
                    logger.info(f"Phase {i}: awaiting human approval")
                    break  # 等待人工审批

                if status == PhaseStatus.FAILED:
                    logger.warning(f"Phase {i}: quality gate failed")
                    break

            except TextCLITaskError as e:
                logger.error(f"Phase {i} failed: TextCLI error — {e}")
                pipeline.add_quality_gate(
                    phase.index, "execution_result", "failed",
                    f"text-cli error: {e.detail}",
                )
                phase.status = PhaseStatus.FAILED
                break

            except TimeoutError as e:
                logger.error(f"Phase {i} timed out: {e}")
                pipeline.add_quality_gate(
                    phase.index, "execution_result", "failed",
                    f"timeout: {e}",
                )
                phase.status = PhaseStatus.FAILED
                break

            except Exception as e:
                logger.error(f"Phase {i} failed: {e}")
                pipeline.add_quality_gate(
                    phase.index, "execution_result", "failed",
                    f"unexpected error: {e}",
                )
                phase.status = PhaseStatus.FAILED
                break

        return pipeline
