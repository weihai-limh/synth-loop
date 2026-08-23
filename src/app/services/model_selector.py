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

    def select(self, service: str, logic_category: Optional[str] = None) -> tuple[Optional[str], str]:
        """
        直接透传 service 给 execution_router（_b P5.2 修复：llm_routing 配置为唯一真源）。

        移除硬编码 service_map 白名单——此前它截断未列出的 service（回落 chat），
        导致多模型多场景配置机制无法扩展。现在任意 service 名都透传到 execution_router，
        从 llm_routing 配置读取；未配置的 service（如 normal）由 execution_router 自动
        回落 chat（其 L99-102 fallback 机制），无需白名单。

        Args:
            service: 服务场景名（chat / prompt_chat / task_chain / analysis /
                     planning / summarize / normal / 未来新增场景）
            logic_category: subtype（可选，未来精细化选择的预留维度，当前不参与）

        Returns:
            (endpoint_name, model_name)
        """
        endpoint, model = self._router.resolve_endpoint(service, "primary")
        if endpoint is None:
            logger.error(f"ModelSelector: no endpoint for service '{service}'")
            return None, ""
        return endpoint.name, model
