# -*- coding: utf-8 -*-
"""sl_llm_provider —— 唯一推理收束点（_b P5.1）

依据：`concept_V0_1_2_b 主线 E` + `integration_sl_draft`（推理收束唯一落点）。

职责：在 `downstream_llm` 之上包一层 **async** 唯一推理落点，所有推理路径
（主/相位/工具）收敛到此。核心能力：
- **三档模型映射**（P2）：routing（planning/normal/summarize）→ 模型档。
  planning/summarize 走 `llm_routing` 覆盖档；normal 走 chat 主力默认档。
- **async 桥接**：ck 推理缝暴露到 build_messages 后，此处为 async 推理出口
  （经 downstream_llm.chat / chat_with_degradation），化解 ck sync / sl async 鸿沟。

routing 语义（pk 推理缝三档）：
- "planning"：规划（selector.select("planning")）
- "summarize"：摘要（selector.select("summarize")）
- "normal" / None：普通执行（selector.select("normal") → chat 主力默认）
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from .downstream_llm import get_downstream_llm
from .model_selector import ModelSelector

logger = logging.getLogger(__name__)


class SlLlmProvider:
    """唯一推理收束点（async）：routing → 模型档 → downstream_llm。"""

    def __init__(self, llm: Optional[Any] = None,
                 selector: Optional[ModelSelector] = None) -> None:
        self._llm = llm or get_downstream_llm()
        self._selector = selector or ModelSelector()

    # ── routing → 模型档（P2 三档）──

    def select_model_for_routing(self, routing: Optional[str]) -> tuple[Optional[str], Optional[str]]:
        """routing（pk 推理缝三档）→ (endpoint_name, model)。

        - planning → select("planning")
        - summarize → select("summarize")
        - normal / None → select("normal")（chat 主力默认）
        """
        if routing == "planning":
            return self._selector.select("planning")
        if routing == "summarize":
            return self._selector.select("summarize")
        return self._selector.select("normal")

    # ── async 唯一推理落点 ──

    async def chat(
        self,
        messages: list[dict[str, Any]],
        routing: Optional[str] = None,
        model: Optional[str] = None,
        api_key: Optional[str] = None,
        tools: Optional[list[dict[str, Any]]] = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """唯一推理落点：经 downstream_llm 调下游 LLM。

        routing 决定模型档（P2 三档）；显式 model 优先于 routing 档。
        """
        endpoint_name, routing_model = self.select_model_for_routing(routing)
        effective_model = model or routing_model
        try:
            if endpoint_name and self._llm._execution_router:
                return await self._llm.chat_with_degradation(
                    endpoint_name, messages, model=effective_model,
                    tools=tools, api_key=api_key, **kwargs,
                )
            return await self._llm.chat(
                messages=messages, model=effective_model, tools=tools,
                api_key=api_key, endpoint_name=endpoint_name,
                **kwargs,
            )
        except Exception as e:
            logger.error(f"sl_llm_provider 推理失败 (routing={routing}): {e}")
            raise

    async def chat_stream(
        self,
        messages: list[dict[str, Any]],
        routing: Optional[str] = None,
        model: Optional[str] = None,
        **kwargs: Any,
    ):
        """流式推理落点（SSE）——下游 streaming_handler 复用。"""
        endpoint_name, routing_model = self.select_model_for_routing(routing)
        effective_model = model or routing_model
        return self._llm.stream_openai(
            messages=messages, model=effective_model,
            api_base=self._llm.api_base,
            api_key=kwargs.get("api_key") or self._llm.default_api_key,
        )


# 全局实例
_provider: Optional[SlLlmProvider] = None


def get_sl_llm_provider() -> SlLlmProvider:
    global _provider
    if _provider is None:
        _provider = SlLlmProvider()
    return _provider
