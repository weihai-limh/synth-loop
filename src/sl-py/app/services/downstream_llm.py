"""下游 LLM 调用模块 - 支持多端点池 + ExecutionRouter"""

import logging
from typing import Any, Optional

import httpx

from ..config import get_section

logger = logging.getLogger(__name__)


class DownstreamLLM:
    """下游 LLM 调用客户端（多端点池支持）"""

    def __init__(self) -> None:
        config = get_section("downstream_llm")
        self.api_base = config.get("api_base", "https://api.openai.com/v1")
        self.default_api_key = config.get("api_key", "")
        self.default_model = config.get("default_model", "gpt-4o-mini")
        self.timeout = config.get("timeout", 30)
        self.max_retries = config.get("max_retries", 0)
        
        # Anthropic 配置
        self.anthropic_api_base = config.get("anthropic_api_base", "https://api.anthropic.com")
        self.anthropic_api_key = config.get("anthropic_api_key", "")
        self.anthropic_model = config.get("anthropic_model", "claude-3-opus-20240229")

        # 多端点客户端池
        self._client: Optional[httpx.AsyncClient] = None
        self._anthropic_client: Optional[httpx.AsyncClient] = None
        self._endpoint_clients: dict[str, httpx.AsyncClient] = {}
        self._execution_router = None

    def set_execution_router(self, router):
        """注入 ExecutionRouter，启用多端点路由"""
        self._execution_router = router

    async def _get_endpoint_client(self, endpoint_name: str, base_url: str) -> httpx.AsyncClient:
        """获取或创建指定端点的 HTTP 客户端"""
        if endpoint_name not in self._endpoint_clients:
            self._endpoint_clients[endpoint_name] = httpx.AsyncClient(
                base_url=base_url,
                timeout=self.timeout,
            )
        client = self._endpoint_clients[endpoint_name]
        if client.is_closed:
            self._endpoint_clients[endpoint_name] = httpx.AsyncClient(
                base_url=base_url,
                timeout=self.timeout,
            )
            return self._endpoint_clients[endpoint_name]
        return client

    async def _get_client(self) -> httpx.AsyncClient:
        """获取 HTTP 客户端（延迟初始化）"""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.api_base,
                timeout=self.timeout,
            )
        return self._client
    
    async def _get_anthropic_client(self) -> httpx.AsyncClient:
        """获取 Anthropic HTTP 客户端（延迟初始化）"""
        if self._anthropic_client is None or self._anthropic_client.is_closed:
            self._anthropic_client = httpx.AsyncClient(
                base_url=self.anthropic_api_base,
                timeout=self.timeout,
            )
        return self._anthropic_client

    async def chat_by_endpoint(
        self,
        messages: list[dict[str, Any]],
        endpoint_name: str,
        model: Optional[str] = None,
        tools: Optional[list[dict[str, Any]]] = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """
        通过 ExecutionRouter 指定的端点调用 LLM（多端点路由版本）

        Args:
            messages: 消息列表
            endpoint_name: 端点名称（对应 model_config.yaml 中的 endpoints key）
            model: 模型名称（可选，覆盖路由配置）
            tools: 工具定义列表
            **kwargs: 其他参数

        Returns:
            LLM 响应字典
        """
        if self._execution_router is None:
            raise RuntimeError("ExecutionRouter not set. Call set_execution_router() first.")

        endpoint_cfg = self._execution_router.get_endpoint(endpoint_name)
        if endpoint_cfg is None:
            raise ValueError(f"Unknown endpoint: {endpoint_name}")

        client = await self._get_endpoint_client(endpoint_name, endpoint_cfg.base_url)
        api_key = endpoint_cfg.get_api_key() or self.default_api_key

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        payload: dict[str, Any] = {
            "model": model or self.default_model,
            "messages": messages,
        }

        if tools:
            payload["tools"] = tools

        for key in ["temperature", "max_tokens", "top_p", "tool_choice"]:
            if key in kwargs and kwargs[key] is not None:
                payload[key] = kwargs[key]

        response = await client.post(
            "/chat/completions",
            json=payload,
            headers=headers,
        )
        response.raise_for_status()
        return response.json()

    async def chat(
        self,
        messages: list[dict[str, Any]],
        model: Optional[str] = None,
        tools: Optional[list[dict[str, Any]]] = None,
        api_key: Optional[str] = None,
        endpoint_name: Optional[str] = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """
        调用下游 LLM（OpenAI 格式）

        Args:
            messages: 消息列表
            model: 模型名称
            tools: 工具定义列表
            api_key: API Key（透传或使用默认）
            endpoint_name: 端点名称（可选，指定则路由到对应端点池）
            **kwargs: 其他参数（temperature, max_tokens, top_p 等）

        Returns:
            LLM 响应字典
        """
        # 多端点路由：如果指定了 endpoint_name，使用对应端点
        if endpoint_name and self._execution_router:
            endpoint_cfg = self._execution_router.get_endpoint(endpoint_name)
            if endpoint_cfg:
                client = await self._get_endpoint_client(endpoint_name, endpoint_cfg.base_url)
                effective_api_key = api_key or endpoint_cfg.get_api_key() or self.default_api_key
            else:
                client = await self._get_client()
                effective_api_key = api_key or self.default_api_key
        else:
            client = await self._get_client()
            effective_api_key = api_key or self.default_api_key

        headers = {
            "Authorization": f"Bearer {effective_api_key}",
            "Content-Type": "application/json",
        }

        payload: dict[str, Any] = {
            "model": model or self.default_model,
            "messages": messages,
        }

        if tools:
            payload["tools"] = tools

        # 添加其他参数
        for key in ["temperature", "max_tokens", "top_p", "tool_choice"]:
            if key in kwargs and kwargs[key] is not None:
                payload[key] = kwargs[key]

        response = await client.post(
            "/chat/completions",
            json=payload,
            headers=headers,
        )
        response.raise_for_status()
        return response.json()

    async def chat_with_degradation(
        self,
        service_name: str,
        messages: list[dict[str, Any]],
        model: Optional[str] = None,
        tools: Optional[list[dict[str, Any]]] = None,
        api_key: Optional[str] = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """_a P3.3: 带两级降级的 LLM 调用（模型级 + 端点级）

        错误码语义（网关接入后）：
        - 503（模型不可用）→ 同池切模型（下一级 fallback 的 model）
        - 502/504（后端/超时）→ 切端点（下一级 endpoint）
        - 参数错/鉴权败 → 不降级（直接上抛）

        降级链：primary → fallback → degradation；每级内先试同 endpoint 不同 model（若配置），
        再切 endpoint。全部耗尽 → 上抛最后错误。
        """
        if not self._execution_router:
            return await self.chat(messages, model=model, tools=tools, api_key=api_key, **kwargs)

        levels = ["primary", "fallback", "degradation"]
        last_exc: Optional[Exception] = None

        for level in levels:
            try:
                endpoint_cfg, level_model = self._execution_router.resolve_endpoint(service_name, level)
                if not endpoint_cfg:
                    continue
                client = await self._get_endpoint_client(endpoint_cfg.name, endpoint_cfg.base_url)
                effective_api_key = api_key or endpoint_cfg.get_api_key() or self.default_api_key
                headers = {
                    "Authorization": f"Bearer {effective_api_key}",
                    "Content-Type": "application/json",
                }
                payload: dict[str, Any] = {
                    "model": model or level_model or self.default_model,
                    "messages": messages,
                }
                if tools:
                    payload["tools"] = tools
                for key in ["temperature", "max_tokens", "top_p", "tool_choice"]:
                    if key in kwargs and kwargs[key] is not None:
                        payload[key] = kwargs[key]

                resp = await client.post("/chat/completions", json=payload, headers=headers)
                if resp.status_code == 503:
                    # 模型不可用 → 同池切模型（下一级）
                    last_exc = httpx.HTTPStatusError(f"503 model unavailable at {level}", request=resp.request, response=resp)
                    logger.warning(f"LLM 503 @ {service_name}/{level} (model unavailable), switching to next tier")
                    continue
                if resp.status_code in (502, 504):
                    # 后端/超时 → 切端点（下一级）
                    last_exc = httpx.HTTPStatusError(f"{resp.status_code} backend error at {level}", request=resp.request, response=resp)
                    logger.warning(f"LLM {resp.status_code} @ {service_name}/{level} (backend/timeout), switching to next tier")
                    continue
                resp.raise_for_status()
                return resp.json()
            except httpx.HTTPStatusError as e:
                # 参数错/鉴权败 → 不降级
                if e.response.status_code in (400, 401, 403, 422):
                    raise
                last_exc = e
                logger.warning(f"LLM call failed @ {service_name}/{level}: {e}, switching to next tier")
            except httpx.HTTPError as e:
                last_exc = e
                logger.warning(f"LLM endpoint unreachable @ {service_name}/{level}: {e}, switching to next tier")

        raise last_exc or RuntimeError(f"LLM 降级链耗尽: {service_name}")

    async def chat_anthropic(
        self,
        messages: list[dict[str, Any]],
        model: Optional[str] = None,
        system: Optional[str] = None,
        tools: Optional[list[dict[str, Any]]] = None,
        api_key: Optional[str] = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """
        调用下游 LLM（Anthropic 格式）

        Args:
            messages: 消息列表
            model: 模型名称
            system: 系统提示
            tools: 工具定义列表
            api_key: API Key
            **kwargs: 其他参数（temperature, max_tokens, top_p 等）

        Returns:
            Anthropic 格式的 LLM 响应字典
        """
        client = await self._get_anthropic_client()

        headers = {
            "x-api-key": api_key or self.anthropic_api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }

        payload: dict[str, Any] = {
            "model": model or self.anthropic_model,
            "messages": messages,
            "max_tokens": kwargs.get("max_tokens", 1024),
        }
        
        if system:
            payload["system"] = system
        
        if tools:
            payload["tools"] = tools

        # 添加其他参数
        for key in ["temperature", "top_p", "stop_sequences"]:
            if key in kwargs and kwargs[key] is not None:
                payload[key] = kwargs[key]

        response = await client.post(
            "/v1/messages",
            json=payload,
            headers=headers,
        )
        response.raise_for_status()
        return response.json()

    async def close(self) -> None:
        """关闭所有 HTTP 客户端"""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
        if self._anthropic_client and not self._anthropic_client.is_closed:
            await self._anthropic_client.aclose()
        for name, client in self._endpoint_clients.items():
            if not client.is_closed:
                await client.aclose()
        self._endpoint_clients.clear()


# 全局实例
_llm: Optional[DownstreamLLM] = None


def get_downstream_llm() -> DownstreamLLM:
    """获取下游 LLM 客户端实例"""
    global _llm
    if _llm is None:
        _llm = DownstreamLLM()
    return _llm
