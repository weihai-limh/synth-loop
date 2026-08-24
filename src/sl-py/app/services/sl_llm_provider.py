# -*- coding: utf-8 -*-
"""sl_llm_provider —— 唯一推理收束点（_b P5.1 + P5.2 归并，所有 chat 路径过闸）

依据：`concept_V0_1_2_b 主线 E` + `integration_sl_draft`（推理收束唯一落点）+ 用户裁决
（5.2 主路径归并进 build_messages 收束点；**所有 chat 上下文都要过 ck 闸**——为未来自动化优化留可能）。

职责：
- **唯一推理落点**：所有路径（主 chat/prompt_chat/fractal/task_chain + 相位 planning/normal/summarize）
  收敛到此，经 `downstream_llm` 调下游 LLM。
- **通用 service 选择**：主路径传 complexity（chat/prompt_chat/task_chain/...）、相位传
  routing（planning/summarize/normal）→ 统一经 `model_selector.select(service)` 选模型。
- **context_id 生成 + ck 闸集成**：主路径也生成 context_id；若 ck gate_mode == auto → 
  `build_passthrough(messages)` → ck `gate_park.park` → 返回 `{gate:"pending", context_id, context}`
  （等闸干预，peek/amend 后再 gate_set 出结果）；若 closed → 直接推理。
  这样所有 chat 上下文可被 ck 闸监听/优化。

gate 返回（开闸时）：
  {gate: "pending", context_id: str, context: {region: {次序: content}}}
closed 返回：
  下游 LLM 响应 dict（choices/usage 等）。
"""

from __future__ import annotations

import logging
from typing import Any, Optional
from uuid import uuid4

from .downstream_llm import get_downstream_llm
from .model_selector import ModelSelector

logger = logging.getLogger(__name__)


class SlLlmProvider:
    """唯一推理收束点：通用 service 选择 + ck 闸集成 + context_id 生成。"""

    def __init__(self, llm: Optional[Any] = None,
                 selector: Optional[ModelSelector] = None,
                 ck: Optional[Any] = None) -> None:
        self._llm = llm or get_downstream_llm()
        self._selector = selector or ModelSelector()
        self._ck = ck  # vendored ck 内核（可选；注入后启用 ck 闸）

    # ── ck 内核注入（启用 ck 闸，所有 chat 路径过闸）──

    def set_ck(self, ck: Optional[Any]) -> None:
        """注入 vendored ck 内核（开闸时所有 chat 上下文可被 ck 闸监听/优化）"""
        self._ck = ck

    # ── context_id 生成（统一函数）──

    def generate_context_id(self) -> str:
        """生成 context_id（所有 chat 路径共用；开闸时在调用时拿一个 id）"""
        return uuid4().hex

    # ── 通用 service 选择 ──

    def select_model(
        self, service: Optional[str], logic_category: Optional[str] = None
    ) -> tuple[Optional[str], str]:
        """service（complexity 或 routing）→ (endpoint_name, model)。

        v0_1_2_d (B3): 支持可选 logic_category（subtype）参与路由；
        命中逻辑细分时优先于 service 维度，未命中回落 service 默认。
        解析失败（未知 logic_category）→ selector 内部告警并回落，等价于落 general_qa。

        - 相位 routing：planning / summarize / normal（normal→chat 主力默认，P2）
        - 主路径 complexity：chat / prompt_chat / task_chain / ...
        - None → chat 默认
        """
        try:
            return self._selector.select(service or "chat", logic_category)
        except Exception as e:
            logger.error(f"sl_llm_provider: model select failed (service={service}, logic={logic_category}): {e}; 回落 chat")
            return self._selector.select("chat")

    # ── async 唯一推理落点 ──

    async def chat(
        self,
        messages: list[dict[str, Any]],
        service: Optional[str] = None,
        model: Optional[str] = None,
        api_key: Optional[str] = None,
        tools: Optional[list[dict[str, Any]]] = None,
        context_id: Optional[str] = None,
        session_id: Optional[str] = None,
        ext: Optional[dict[str, Any]] = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """唯一推理落点。service 决定模型档；显式 model 优先。

        开闸（ck gate_mode == auto）：生成 context_id + ck park → 返回 pending（等闸干预）。
        关闸（closed）：直接推理返回下游响应。
        """
        # ck 闸集成：开闸时 park 返回 pending（所有 chat 上下文过闸）
        if self._ck is not None:
            from ..kernels.context_kernel.core.assembler import build_passthrough
            from ..kernels.context_kernel.core.gate import extract_custom_context
            from ..kernels.context_kernel.core.models import GateMode
            if self._ck.gate_mode == GateMode.AUTO:
                cid = context_id or self.generate_context_id()
                assembled = build_passthrough(messages)
                parked_id = self._ck.gate_park.park(
                    assembled=assembled,
                    session_view=None,
                    ext=ext,
                    model=model,
                    session_id=session_id,
                )
                custom = extract_custom_context(assembled)
                logger.info(f"sl_llm_provider: 开闸 park (context_id={parked_id}, service={service})")
                return {
                    "gate": "pending",
                    "context_id": parked_id,
                    "context": custom.to_dict()["regions"],
                }

        # closed：直接推理（经 downstream_llm，多端点/降级）
        endpoint_name, service_model = self.select_model(service)
        effective_model = model or service_model
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
            logger.error(f"sl_llm_provider 推理失败 (service={service}): {e}")
            raise

    async def chat_stream(
        self,
        messages: list[dict[str, Any]],
        service: Optional[str] = None,
        model: Optional[str] = None,
        **kwargs: Any,
    ):
        """流式推理落点（SSE，经 StreamingHandler.stream_openai）。"""
        from .streaming_handler import StreamingHandler
        endpoint_name, service_model = self.select_model(service)
        effective_model = model or service_model
        return StreamingHandler.stream_openai(
            messages=messages, model=effective_model,
            api_base=self._llm.api_base,
            api_key=kwargs.get("api_key") or self._llm.default_api_key,
        )

    # ── 兼容旧 routing 调用（SlInferenceSeam 曾用 select_model_for_routing）──

    def select_model_for_routing(self, routing: Optional[str]) -> tuple[Optional[str], str]:
        """routing 三档 → model（向后兼容相位推理缝调用）。"""
        return self.select_model(routing)


# 全局实例
_provider: Optional[SlLlmProvider] = None


def get_sl_llm_provider() -> SlLlmProvider:
    global _provider
    if _provider is None:
        _provider = SlLlmProvider()
    return _provider
