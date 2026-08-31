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
        基于 service + logic_category 选择模型。

        v0_1_2_d (B3): logic_category 命中 → 直查 logic_categories 细分路由（优先）；
        未命中（None / 未知 logic_category）→ 回落 service 默认路由。
        移除硬编码 service_map 白名单——llm_routing 配置为唯一真源。

        Args:
            service: 服务场景名（chat / prompt_chat / task_chain / analysis /
                     planning / summarize / normal / 未来新增场景）
            logic_category: subtype（document_writing / code_generation / ...），
                            命中时优先于 service 维度

        Returns:
            (endpoint_name, model_name)
        """
        # 1. logic_category 直查（命中优先）
        if logic_category:
            endpoint, model = self._router.resolve_logic_endpoint(logic_category, "primary")
            if endpoint is not None:
                return endpoint.name, model
            logger.info(f"ModelSelector: logic_category '{logic_category}' not configured, falling back to service '{service}'")

        # 2. 回落 service 默认路由
        endpoint, model = self._router.resolve_endpoint(service, "primary")
        if endpoint is None:
            logger.error(f"ModelSelector: no endpoint for service '{service}'")
            return None, ""
        return endpoint.name, model
