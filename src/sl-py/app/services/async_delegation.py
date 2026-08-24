"""异步委托 text-cli（_a P4 收敛）——委托/轮询经强化客户端

旧实现（v0.1.2）：自建 httpx POST + 读 rst_data.text 旧嵌套（P15 根因——delegate 拿不到 task_id）。
新实现（_a）：delegate/poll 收敛为强化客户端调用（SPEC 1.3.2 信封直读 + task.state 五态），
不再自建 httpx、不再读旧信封格式。
"""

import asyncio
import json
import logging
from typing import Any, Optional

from ..models.pipeline import PipelineSession, PhaseDefinition, PhaseStatus
from .textcli_enhanced_client import EnhancedTextCliClient, TextCLITaskError, get_enhanced_client

logger = logging.getLogger(__name__)


class AsyncDelegationService:
    """异步委托服务——委托 text-cli 执行相位任务（收敛为强化客户端）"""

    def __init__(self, client: Optional[EnhancedTextCliClient] = None):
        self.client = client or get_enhanced_client()  # 注入强化客户端（不再自建 httpx）

    async def delegate_to_textcli(self, step_name: str, path_json: dict,
                                  alias: Optional[str] = None) -> str:
        """调 text-cli --async → 返回 task_id（经强化客户端，信封直读——P15 修复）"""
        prompt = f"AI:text-cli;path,{json.dumps(path_json, ensure_ascii=False)},--async"
        try:
            result = await self.client.call(prompt, alias=alias)
            if not result.ok:
                raise TextCLITaskError(task_id="?", detail=f"delegate failed: {result.rst_err}")
            if not result.is_async:
                raise TextCLITaskError(task_id="?", detail=f"expected async, got: {result.data}")
            task_id = result.data["task_id"]  # 直读 rst_data.task_id（P15 修复）
            logger.info(f"Delegated to text-cli: {step_name} → task_id={task_id}")
            return task_id
        except Exception as e:
            logger.error(f"Delegate to text-cli failed: {e}")
            raise

    async def poll_textcli_task(self, task_id: str, *, timeout: int = 300) -> dict:
        """轮询——经强化客户端 wait（task.state 五态，指数退避）"""
        result = await self.client.wait(task_id, timeout=timeout)
        if not result.ok:
            raise TextCLITaskError(task_id=task_id, detail=result.rst_err)
        return result.data

    # v0_1_2_d (M3): 旧 PhaseExecutor 依赖已剥离——execute_phase / confirm_path 旧相位编排
    # 随 phase_executor.py 删除一并移除；T8 相位执行改由 TaskChainService（M4）统一驱动。
