"""
ModelSelector - Phase 3: GW-P2 Dispatch
基于 complexity + logic_category 查 llm_routing 选模型。
"""
import logging
from typing import Optional

from .execution_router import ExecutionRouter, get_execution_router

logger = logging.getLogger(__name__)


class ModelSelector:
    """模型选择器"""

    def __init__(self, router: Optional[ExecutionRouter] = None):
        self._router = router or get_execution_router()

    def select(self, complexity: str, logic_category: Optional[str] = None) -> tuple[Optional[str], str]:
        """
        根据 complexity 级别选择模型

        Args:
            complexity: chat / prompt_chat / task_chain / planning / summarize
            logic_category: subtype（可选，用于精细化选择）

        Returns:
            (endpoint_name, model_name)
        """
        # 映射：complexity → llm_routing service name（_a P3: 4→6 场景；_b P2: normal=chat 主力默认）
        service_map = {
            "chat": "chat",
            "prompt_chat": "prompt_chat",
            "task_chain": "task_chain",
            "analysis": "analysis",
            "planning": "planning",
            "summarize": "summarize",
            "normal": "chat",  # _b P2：normal（pk 普通执行）= chat 场景（主力默认模型）
        }
        service_name = service_map.get(complexity, "chat")

        endpoint, model = self._router.resolve_endpoint(service_name, "primary")
        if endpoint is None:
            logger.error(f"ModelSelector: no endpoint for service '{service_name}'")
            return None, ""
        return endpoint.name, model
