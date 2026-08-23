# -*- coding: utf-8 -*-
"""SlInferenceSeam —— pk 推理缝（sl 填缝，_b P5.1）

依据：`concept_V0_1_2_b §六-3`（推理缝集成点 = build_messages，非 ck）+ `主线 E`。

目的（用户澄清）：**让 ck 的闸能监听每个相位的推理上下文**——推理缝暴露到
`build_messages`，每次 pk 推理（planning/normal/summarize）都经 ck 拼装 +
闸监听，再 async 推理出 content 回填 pk。

链路：
  pk 推理缝（_plan_with_seam / _execute_phase / _produce_summary）
    → SlInferenceSeam.infer(context_patch)      [async，本类]
    → build_messages 收束                          [经 ck build_prompt 拼装 + 闸监听]
    → sl_llm_provider                              [async 唯一推理落点]
    → 回填 InferenceResult（context_id/phase_path 一致）

语义：本类是推理缝（inference_seam），**不是** ContextKernel 子类——保持语义
纯净，防腐败（推理缝 ≠ 上下文内核）。SlContextKernel 仅作 ck 组件实例供适配器用。
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from ..kernels.context_kernel.core.assembler import build_prompt
from ..kernels.context_kernel.core.models import InferenceResult, SessionView
from .sl_llm_provider import SlLlmProvider, get_sl_llm_provider

logger = logging.getLogger(__name__)


class SlInferenceSeam:
    """pk 推理缝（sl 填缝）：context_patch → build_messages 收束 → async 推理 → InferenceResult。

    三处推理用途（pk routing）都经此：
      planning / normal / summarize → sl_llm_provider 三档模型。
    """

    def __init__(
        self,
        context_source: Any,
        llm_provider: Optional[SlLlmProvider] = None,
        gate_manager: Optional[Any] = None,
    ) -> None:
        self.context_source = context_source      # ck ContextSource（读会话快照）
        self.llm_provider = llm_provider or get_sl_llm_provider()
        self.gate_manager = gate_manager          # gate_manager（经它走 ck 闸，可 None）

    async def infer(self, context_patch: Any) -> InferenceResult:
        """pk 推理缝契约：infer(context_patch) -> inference_result。

        context_patch（pk 契约，phase_path 已 str）：
          {phase_path: str, intent, context_id, ext: {routing}}
        """
        patch = context_patch
        ext = getattr(patch, "ext", None) or {}
        routing = ext.get("routing")
        intent = getattr(patch, "intent", None)
        context_id = getattr(patch, "context_id", None)
        session_id = context_id or ""
        phase_path = getattr(patch, "phase_path", None)

        # 1. 取会话快照（ck ContextSource）
        session_view = self.context_source.read_session(session_id)

        # 2. build_messages 收束：经 ck build_prompt 六层拼装（同步纯函数，复用 ck）
        assembled = build_prompt(
            session_view,
            current_user_content=intent,
            session_id=session_id,
            routing=routing,
        )
        messages = assembled.messages

        # 3. 经 gate_manager 走 ck 闸监听（若注入 gate_manager，且 active_combo 含 intervention）
        if self.gate_manager is not None and self.gate_manager.ck is not None:
            # 若当前组合含 intervention，且 context_id 有 park 快照 → 先 peek/amend
            combo = self.gate_manager.get_config().get("active_combo", "all_off")
            if combo != "all_off" and "intervention" in combo:
                try:
                    # 经 gate_manager 的 intervention 闸（peek/amend 旁路监听）
                    gate_resp = self.gate_manager._intervention_apply(context_id, None)
                    if gate_resp.data:
                        logger.info(f"SlInferenceSeam: ck 闸监听相位上下文 (context_id={context_id}, routing={routing})")
                except Exception as e:
                    logger.warning(f"SlInferenceSeam: ck 闸监听跳过: {e}")

        # 4. async 唯一推理落点（service=routing → 三档模型；routing 即服务场景）
        response = await self.llm_provider.chat(messages, service=routing)

        # 5. 回填 InferenceResult（content / context_id / phase_path 一致）
        choice = response.get("choices", [{}])[0]
        message = choice.get("message", {})
        return InferenceResult(
            context_id=context_id or "",
            content=message.get("content"),
            result_ref=ext.get("result_ref"),
            ext={"routing": routing, "phase_path": phase_path,
                 "model": response.get("model"),
                 "usage": response.get("usage")},
            tool_calls=message.get("tool_calls"),
        )
