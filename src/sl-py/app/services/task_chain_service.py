"""任务链服务（Task Chain Service，M4 / v0_1_2_d Phase 8）。

v0_1_2_d 重构：旧 ``TaskChainExecutor``（#6 红线）已删除，T8 相位执行改由本服务统一驱动。
职责（design §三 3.2 / §四 4.3）：
1. 构建 tc path 信封（对齐 text-cli-path-v1 schema，经 DEFAULT_TC_ALIAS 路由）
2. 写 tasks 表（G3 闭环：落库责任由本服务承接，取代旧 _delegate_to_textcli 的写表）
3. 委托 text-cli --async（经 AsyncDelegationService，复用 M1 统一通道）
4. 轮询结果
5. 确认闸（M2 已开 async，M3 已清旧相位执行器；此处派发确认任务并等待）
6. 回写 tasks 表（status/result）
"""

import json
import logging
import time
import uuid
from typing import Any, Optional

from ..database import execute_write, get_shared_db
from .async_delegation import AsyncDelegationService

logger = logging.getLogger(__name__)

# text-cli 的 tc 默认别名（对齐 design §三 3.2；运行时表须有该 alias 行）
DEFAULT_TC_ALIAS = "fractal-default"

# tasks 表写状态常量
STATUS_QUEUED = "queued"
STATUS_RUNNING = "running"
STATUS_COMPLETED = "completed"
STATUS_ERROR = "error"


class TaskChainService:
    """任务链服务——T8 相位执行统一驱动 + G3 落库责任承接。"""

    def __init__(self, delegation: Optional[AsyncDelegationService] = None):
        self._delegation = delegation or AsyncDelegationService()

    # ──────────────────────────────────────────────────────────────
    # 主入口
    # ──────────────────────────────────────────────────────────────

    async def run(
        self,
        user_text: str,
        session: Any,
        level: str,
        logic_category: Optional[str] = None,
        api_key: Optional[str] = None,
        *,
        timeout: int = 300,
    ) -> dict[str, Any]:
        """执行一次 task_chain（sl 直接经 text-cli 编排，不依赖旧相位执行器）。

        Returns:
            OpenAI chat.completion 格式响应 dict。
        """
        session_id = getattr(session, "session_id", None)
        user_id = getattr(session, "user_id", None)
        task_id = f"Task-{uuid.uuid4().hex[:8]}-synthloop"

        # [1] 构建 tc path 信封（对齐 text-cli-path-v1）
        path_json = self._build_path_envelope(user_text, level, logic_category)
        logger.info(f"[M4-TC] build path task_id={task_id} alias={DEFAULT_TC_ALIAS} level={level}")

        # [2] 写 tasks 表（queued）→ G3 落库责任承接
        await self._write_task(
            task_id, session_id, user_id, user_text, STATUS_QUEUED,
            {"path_json": path_json, "text_cli_task_id": None, "confirmed": False},
        )

        try:
            # [3] 委托 text-cli --async（经 M1 统一通道）
            logger.info(f"[M4-TC] delegate task_id={task_id} level={level}")
            text_cli_task_id = await self._delegation.delegate_to_textcli(
                step_name=f"fractal-{level}", path_json=path_json, alias=DEFAULT_TC_ALIAS
            )
            await self._write_task_status(task_id, STATUS_RUNNING,
                                          {"text_cli_task_id": text_cli_task_id})

            # [4] 轮询结果
            logger.info(f"[M4-TC] poll task_id={task_id} text_cli_task_id={text_cli_task_id}")
            result_data = await self._delegation.poll_textcli_task(text_cli_task_id, timeout=timeout)

            # [5] 确认闸（M2 已开 async；M3 已清旧相位执行器）
            confirmed = await self._dispatch_confirm(
                task_id, text_cli_task_id, user_text, level, logic_category
            )

            # [6] 回写 tasks 表（completed）
            result_json = {
                "text_cli_task_id": text_cli_task_id,
                "confirmed": confirmed,
                "summary": result_data.get("summary") if isinstance(result_data, dict) else str(result_data),
            }
            await self._write_task_status(task_id, STATUS_COMPLETED, result_json)
            logger.info(f"[M4-TC] done task_id={task_id} confirmed={confirmed}")

            return self._build_response(task_id, text_cli_task_id, result_json, level)

        except Exception as e:
            logger.error(f"[M4-TC] failed task_id={task_id} level={level}: {e}")
            await self._write_task_status(task_id, STATUS_ERROR, {"error": str(e)})
            return self._build_error_response(task_id, level, str(e))

    # ──────────────────────────────────────────────────────────────
    # 内部：path 信封 / 确认闸 / 落库 / 响应
    # ──────────────────────────────────────────────────────────────

    def _build_path_envelope(
        self, user_text: str, level: str, logic_category: Optional[str]
    ) -> dict[str, Any]:
        """构建对齐 text-cli-path-v1 的 tc path 信封。"""
        return {
            "id": f"tc-{uuid.uuid4().hex[:8]}",
            "name": f"fractal-{level}",
            "type": "pipeline",
            "version": "0.1.0",
            "mode": "toolchain",
            "description": f"sl task_chain dispatch (level={level}, logic={logic_category})",
            "requires": [],
            "steps": [{
                "id": "step_1",
                "instruction": user_text,
                "output_as": "step_1",
            }],
            "_schema": "text-cli-path-v1",
            "_logic_category": logic_category,
        }

    async def _dispatch_confirm(
        self, task_id: str, text_cli_task_id: str, user_text: str,
        level: str, logic_category: Optional[str],
    ) -> bool:
        """确认闸：派发一个确认任务给 text-cli（M2 已开 async）。

        返回是否确认成功；失败仅告警不阻断主链路（确认闸为增强语义，非硬依赖）。
        """
        confirm_path = {
            "id": f"confirm-{uuid.uuid4().hex[:8]}",
            "name": f"fractal-{level}-confirm",
            "type": "pipeline",
            "version": "0.1.0",
            "mode": "toolchain",
            "description": "task_chain 确认闸（sl 直接确认，非旧相位执行器）",
            "requires": [text_cli_task_id],
            "steps": [{
                "id": "confirm_step",
                "instruction": f"确认任务 {text_cli_task_id} 完成（user_ask={user_text[:200]}）",
                "output_as": "confirm_step",
            }],
            "_schema": "text-cli-path-v1",
            "_confirm_of": text_cli_task_id,
            "_confirm": True,
        }
        try:
            logger.info(f"[M4-TC] confirm dispatch task_id={task_id} text_cli_task_id={text_cli_task_id}")
            confirm_task_id = await self._delegation.delegate_to_textcli(
                step_name=f"fractal-{level}-confirm", path_json=confirm_path, alias=DEFAULT_TC_ALIAS
            )
            await self._delegation.poll_textcli_task(confirm_task_id, timeout=60)
            logger.info(f"[M4-TC] confirm ok task_id={task_id} confirm_task_id={confirm_task_id}")
            return True
        except Exception as e:
            logger.warning(f"[M4-TC] confirm gate failed (non-blocking) task_id={task_id}: {e}")
            return False

    async def _write_task(
        self, task_id: str, session_id: Optional[str], user_id: Optional[str],
        user_text: str, status: str, result: dict[str, Any],
    ) -> None:
        """写 tasks 表（G3 闭环：落库责任承接）。"""
        db = await get_shared_db()
        await execute_write(
            db,
            """INSERT INTO tasks (id, session_id, user_id, input, status, result, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)""",
            (task_id, session_id, user_id, user_text, status, json.dumps(result, ensure_ascii=False)),
        )

    async def _write_task_status(self, task_id: str, status: str, result_patch: dict[str, Any]) -> None:
        """更新 tasks 表 status + result（合并既有 result）。"""
        db = await get_shared_db()
        cur = await execute_write(
            db, "SELECT result FROM tasks WHERE id = ?", (task_id,)
        )
        row = await cur.fetchone()
        merged = {}
        if row and row["result"]:
            try:
                merged = json.loads(row["result"])
            except (json.JSONDecodeError, TypeError):
                merged = {}
        merged.update(result_patch)
        await execute_write(
            db,
            """UPDATE tasks SET status = ?, result = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?""",
            (status, json.dumps(merged, ensure_ascii=False), task_id),
        )

    def _build_response(
        self, task_id: str, text_cli_task_id: str, result_json: dict[str, Any], level: str
    ) -> dict[str, Any]:
        summary = result_json.get("summary", "")
        confirmed = result_json.get("confirmed", False)
        content = (
            f"✅ Task chain completed (task_id={task_id}, text_cli_task_id={text_cli_task_id}).\n"
            f"确认闸: {'已确认' if confirmed else '未确认（非阻断）'}.\n"
            f"{summary}"
        )
        return {
            "id": f"chain-{task_id}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": f"fractal-{level}",
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            "_task_id": task_id,
            "_text_cli_task_id": text_cli_task_id,
        }

    def _build_error_response(self, task_id: str, level: str, error: str) -> dict[str, Any]:
        return {
            "id": f"chain-err-{task_id}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": f"fractal-{level}",
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": f"⚠ task_chain 执行失败：{error}"},
                "finish_reason": "stop",
            }],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            "_task_id": task_id,
            "_error": error,
        }
