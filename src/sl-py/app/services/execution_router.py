"""
ExecutionRouter - 多端点路由服务
加载 model_config.yaml，按 service name 查找 primary/fallback/degradation 端点。
"""

import os
import logging
from pathlib import Path
from typing import Any, Optional

import yaml

logger = logging.getLogger(__name__)


def _load_subtype_names(rules_path: Path) -> set[str]:
    """从 complexity_rules.yaml 的 subtypes 段读取合法枚举名（真源）"""
    if not rules_path.exists():
        return set()
    with open(rules_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return {item.get("name") for item in data.get("subtypes", []) or [] if item.get("name")}


class EndpointConfig:
    """端点配置"""

    def __init__(self, name: str, config: dict):
        self.name = name
        self.base_url: str = config.get("base_url", "")
        self.api_key_env: str = config.get("api_key_env", "")
        self.description: str = config.get("description", "")

    def get_api_key(self) -> str:
        """从环境变量读取 API Key"""
        if self.api_key_env:
            return os.getenv(self.api_key_env, "")
        return ""


class RoutingLevel:
    """路由层级：primary / fallback / degradation"""

    def __init__(self, level_config: dict, endpoints: dict[str, EndpointConfig]):
        self.endpoint_name: str = level_config.get("endpoint", "")
        self.model: str = level_config.get("model", "")
        self.endpoint: Optional[EndpointConfig] = endpoints.get(self.endpoint_name)


class ServiceRouting:
    """每个 service 的完整路由配置"""

    def __init__(self, service_name: str, routing_config: dict, endpoints: dict[str, EndpointConfig]):
        self.service_name = service_name
        self.primary = RoutingLevel(routing_config.get("primary", {}), endpoints)
        self.fallback = RoutingLevel(routing_config.get("fallback", {}), endpoints)
        self.degradation = RoutingLevel(routing_config.get("degradation", {}), endpoints)


class ExecutionRouter:
    """多端点执行路由器"""

    def __init__(self, config_path: Optional[str] = None):
        self._endpoints: dict[str, EndpointConfig] = {}
        self._routings: dict[str, ServiceRouting] = {}
        self._logic_routings: dict[str, ServiceRouting] = {}
        if config_path:
            self.load_config(config_path)

    def load_config(self, config_path: str):
        """加载 model_config.yaml"""
        path = Path(config_path)
        if not path.exists():
            raise FileNotFoundError(f"model_config.yaml not found: {config_path}")

        with open(path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f) or {}

        # 加载端点池
        endpoints_raw = config.get("endpoints", {})
        self._endpoints = {
            name: EndpointConfig(name, cfg)
            for name, cfg in endpoints_raw.items()
        }
        logger.info(f"Loaded {len(self._endpoints)} endpoints from {config_path}")

        # 加载路由配置
        routing_raw = config.get("llm_routing", {})
        self._routings = {
            name: ServiceRouting(name, cfg, self._endpoints)
            for name, cfg in routing_raw.items()
        }
        logger.info(f"Loaded {len(self._routings)} service routings: {list(self._routings.keys())}")

        # v0_1_2_d (B3): 加载 logic_category 细分路由（key ⊆ complexity_rules.yaml subtypes[].name）
        rules_path = path.parent / "complexity_rules.yaml"
        valid_subtypes = _load_subtype_names(rules_path)
        logic_raw = config.get("logic_categories", {})
        if logic_raw:
            self._logic_routings = {
                name: ServiceRouting(name, cfg, self._endpoints)
                for name, cfg in logic_raw.items()
            }
            # 枚举校验：logic_categories 的 key 必须是 subtypes 真源子集
            unknown = set(self._logic_routings.keys()) - valid_subtypes
            if unknown:
                raise ValueError(
                    f"logic_categories 含未知 subtype（不在 complexity_rules.yaml subtypes 真源中）: {unknown}"
                )
            logger.info(f"Loaded {len(self._logic_routings)} logic_category routings: {list(self._logic_routings.keys())}")

    def get_routing(self, service_name: str) -> Optional[ServiceRouting]:
        """获取指定 service 的路由配置"""
        return self._routings.get(service_name)

    def get_endpoint(self, endpoint_name: str) -> Optional[EndpointConfig]:
        """获取指定端点配置"""
        return self._endpoints.get(endpoint_name)

    def get_logic_routing(self, logic_category: str) -> Optional[ServiceRouting]:
        """获取指定 logic_category 的路由配置"""
        return self._logic_routings.get(logic_category)

    def resolve_logic_endpoint(self, logic_category: str, level: str = "primary") -> tuple[Optional[EndpointConfig], str]:
        """
        v0_1_2_d (B3): 按 logic_category 直查细分路由。
        - 返回 (EndpointConfig, model_name)；未配置该 logic_category 时返回 (None, "")
        - 命中意味着 logic_category 维度优先于 service 维度
        """
        routing = self.get_logic_routing(logic_category)
        if not routing:
            return None, ""
        level_attr = getattr(routing, level, None)
        if level_attr and level_attr.endpoint:
            return level_attr.endpoint, level_attr.model
        if level == "primary" and routing.fallback.endpoint:
            logger.warning(f"Primary endpoint not available for logic '{logic_category}', fallback to fallback")
            return routing.fallback.endpoint, routing.fallback.model
        elif level in ("primary", "fallback") and routing.degradation.endpoint:
            logger.warning(f"Falling back to degradation for logic '{logic_category}'")
            return routing.degradation.endpoint, routing.degradation.model
        return None, ""

    def resolve_endpoint(self, service_name: str, level: str = "primary") -> tuple[Optional[EndpointConfig], str]:
        """
        解析端点：
        - 返回 (EndpointConfig, model_name)
        - level: "primary" | "fallback" | "degradation"
        """
        routing = self.get_routing(service_name)
        if not routing:
            # fallback：使用 main_gateway 的对应级别
            routing = self.get_routing("chat")

        if not routing:
            raise ValueError(f"No routing found for service '{service_name}' and no fallback")

        level_attr = getattr(routing, level, None)
        if level_attr and level_attr.endpoint:
            return level_attr.endpoint, level_attr.model

        # 降级链：尝试下一级
        if level == "primary" and routing.fallback.endpoint:
            logger.warning(f"Primary endpoint not available for '{service_name}', fallback to fallback")
            return routing.fallback.endpoint, routing.fallback.model
        elif level in ("primary", "fallback") and routing.degradation.endpoint:
            logger.warning(f"Falling back to degradation for '{service_name}'")
            return routing.degradation.endpoint, routing.degradation.model

        raise ValueError(f"No available endpoint for service '{service_name}' at level '{level}'")


# 全局实例
_router: Optional[ExecutionRouter] = None


def get_execution_router(config_path: Optional[str] = None) -> ExecutionRouter:
    """获取 ExecutionRouter 实例"""
    global _router
    if _router is None:
        _router = ExecutionRouter()
        if config_path:
            _router.load_config(config_path)
    return _router
