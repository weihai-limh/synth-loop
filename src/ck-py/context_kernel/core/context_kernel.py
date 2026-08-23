"""ck 标准运行时（core/context_kernel.py）——闸编排唯一实现点（design §5）。

dev-plan §0.3：本 Phase 只落类骨架 + 方法桩（零逻辑）；签名锁定，
P2/P4 填逻辑。core 不持会话写权（design §4.5 写权归属 serve 层）。
"""

from __future__ import annotations

from typing import Any, Optional

from ..core.assembler import build_passthrough, build_prompt
from ..core.models import GateMode, InferenceResult
from ..core.gate import (
    GatePark,
    extract_custom_context,
    reassemble_from_custom,
)
from ..core.gate_config import GateConfig
from ..ports import ContextSource, DataPlane, LlmProvider


class ContextKernel:
    """拼装内核 + 推理闸编排入口（design §5.1）。

    两条入口汇流：infer（组件形态 pk 填缝）/ run_openai（serve 形态）
    都调用 _assemble_and_gate，闸逻辑只写一份（红线⑦）。
    """

    def __init__(
        self,
        context_source: ContextSource,
        data_plane: DataPlane,
        llm_provider: LlmProvider,
        primary_model: str,
        fallback_model: str,
        gate_mode: str | GateMode = "closed",
        context_mode: str = "layered",
    ) -> None:
        self.context_source = context_source
        self.data_plane = data_plane
        self.llm_provider = llm_provider
        self.primary_model = primary_model
        self.fallback_model = fallback_model
        self.gate_park = GatePark()  # 推理闸 park（进程级，瞬时不入库）
        # 服务端全局闸配置（design §1.3：请求无权控闸，配置在.server 端）
        self.gate_config = GateConfig(gate_mode, context_mode)

    @property
    def gate_mode(self) -> GateMode:
        """当前服务端全局闸模式。"""
        return self.gate_config.gate_mode

    def set_gate_mode(self, mode: str | GateMode) -> GateMode:
        """运行时切换闸模式（/context-conf/ 端点，dev-plan §5.3）。"""
        return self.gate_config.set_gate_mode(mode)

    # --- 组件形态入口（pk 填缝方，P4 填逻辑） ---
    def infer(self, context_patch: Any) -> Any:
        """pk 推理缝契约：infer(context_patch) -> inference_result。"""
        raise NotImplementedError("infer: 组件形态 pk 填缝在后续 Phase 填充")

    # --- serve 形态入口（P2 填逻辑） ---
    def run_openai(self, body: dict[str, Any]) -> dict[str, Any]:
        """解析 OpenAI body.metadata → 组装 → 调 _assemble_and_gate（design §5.2）。

        body（OpenAI chat 格式）：
          messages / model / stream / metadata（含 session_id / client_system_messages /
          override_system / ext）
        形态①纯 chat：无前序产物，data_prefix/strategy 留 None。
        """
        metadata = body.get("metadata") or {}
        session_id = metadata.get("session_id")
        client_system_messages = metadata.get("client_system_messages")
        override_system = metadata.get("override_system")
        ext = metadata.get("ext")

        # G1/D1：从 body 顶层提取 model/stream/service_name（缺省回落 ck 默认）
        model = body.get("model")
        stream = body.get("stream", False)
        service_name = (ext or {}).get("service_name")

        # 当前用户内容：取 messages 末条 role==user 的 content（对齐 sl 取 current_user_content）
        current_user_content = None
        for msg in reversed(body.get("messages", [])):
            if msg.get("role") == "user":
                current_user_content = msg.get("content")
                break

        # 此处以 metadata.client_system_messages 为准；body 内 system 不入拼装（防双重注入）
        session_view = self.context_source.read_session(session_id or "")

        # 闸模式：请求 body 不控闸（design §1.3），用服务端全局 gate_mode
        return self._assemble_and_gate(
            session_view=session_view,
            client_system_messages=client_system_messages,
            override_system=override_system,
            current_user_content=current_user_content,
            session_id=session_id,
            ext=ext,
            gate_mode=self.gate_mode,
            raw_messages=body.get("messages") or [],
            model=model,
            stream=stream,
            service_name=service_name,
        )

    # --- 闸编排唯一实现点（P2 关闸 / P4 开闸 填逻辑） ---
    def _assemble_and_gate(
        self,
        session_view: Any,
        client_system_messages: Optional[list[dict[str, Any]]] = None,
        override_system: Optional[str] = None,
        current_user_content: Optional[str] = None,
        session_id: Optional[str] = None,
        routing: Any = None,
        data_prefix: Any = None,
        strategy: Any = None,
        ext: Optional[dict[str, Any]] = None,
        gate_mode: Any = None,
        raw_messages: Optional[list[dict[str, Any]]] = None,
        context_mode: Optional[str] = None,
        model: Optional[str] = None,
        stream: bool = False,
        service_name: Optional[str] = None,
    ) -> Any:
        """assemble + gate 编排；闸逻辑只写一份（红线⑦）。

        closed：拼装 → 直连 LLM → 返回 InferenceResult。
        auto：拼装 → park（生成 context_id）→ 当场返 {context_id, context, gate:"pending"}，不调 LLM。

        context_mode（拼装策略，与 gate_mode 正交）：
        - "layered"（默认）：六层拼装。
        - "passthrough"：通用态，raw_messages 全量映射为 {"context": {次序: 内容}}。
        """
        # 闸模式：显式参数优先，否则取服务端全局配置（design §1.3 服务端配置）
        gate = gate_mode if isinstance(gate_mode, GateMode) else self.gate_config.gate_mode
        # 拼装策略：显式参数优先，否则取服务端全局配置（与 gate_mode 正交）
        mode = context_mode or self.gate_config.context_mode
        if mode == "passthrough":
            assembled = build_passthrough(raw_messages)
        else:
            assembled = build_prompt(
                session_view,
                client_system_messages=client_system_messages,
                override_system=override_system,
                current_user_content=current_user_content,
                session_id=session_id,
                routing=routing,
            )
        if gate == GateMode.AUTO:
            # 开闸：park 不调 LLM（design §4.3）；context_id 瞬时不入库
            context_id = self.gate_park.park(
                assembled=assembled,
                session_view=session_view,
                client_system_messages=client_system_messages,
                override_system=override_system,
                current_user_content=current_user_content,
                session_id=session_id,
                ext=ext,
                model=model,
            )
            custom = extract_custom_context(assembled)
            return {
                "context_id": context_id,
                "context": custom.to_dict()["regions"],
                "gate": "pending",
            }
        # closed：直连 LLM（G1：model 透传，缺省回落 primary；G2：stream 双态；D5 不适用此分支）
        effective_model = model or self.primary_model
        response = self.llm_provider.chat(
            assembled.messages, effective_model, stream=stream, service_name=service_name
        )
        message = response["choices"][0]["message"]
        content = message.get("content")
        # G3 修复：原样透传 tool_calls（分形全部走 ck，丢弃即阻断 sl 经 ck 调工具）
        tool_calls = message.get("tool_calls")
        return InferenceResult(
            context_id=session_id or "",
            content=content,
            result_ref=None,
            ext={"model": effective_model, "usage": response.get("usage")},
            tool_calls=tool_calls,
        )

    # --- 闸两段流（design §3.3 / §4.3）---
    def gate_get(self, context_id: str) -> dict[str, Any]:
        """GET /chatgate/{context_id}：取回 content 视图（CustomContext 区域+次序）。"""
        entry = self.gate_park.get(context_id)
        if entry is None:
            return {"error": "unknown context_id"}
        custom = extract_custom_context(entry["assembled"])
        return {"context_id": context_id, "context": custom.to_dict()["regions"]}

    def gate_set(self, context_id: str, custom: Any) -> InferenceResult:
        """POST /chatgate/{context_id}：修正推 LLM。

        仅改 park 输入快照（reassemble），绝不回调 append_turn（红线⑥）；
        随后用修正后 messages 调 LLM 出结果。
        """
        entry = self.gate_park.get(context_id)
        if entry is None:
            raise KeyError(f"unknown context_id: {context_id}")
        base = entry["assembled"]
        # custom 接受 dict 或 CustomContext
        if isinstance(custom, dict):
            from ..core.models import CustomContext
            custom = CustomContext(regions=custom)
        reassembled = reassemble_from_custom(base, custom)
        # 红线⑥：此处只更新 park 内的 assembled，不触碰 session 写点
        self.gate_park.update_assembled(context_id, reassembled)
        # D5 已决 B：gate_set 恒非流（不读 body stream）；G1 闭环：model 取 park 时记录值，
        # 使开闸修正推与首次模型一致（无外部 body 可重传，沿用 park 上下文）；
        # service_name 在开闸修正推场景无外部来源，按 D1 默认 None 回落
        effective_model = entry.get("model") or self.primary_model
        response = self.llm_provider.chat(
            reassembled.messages, effective_model, stream=False
        )
        message = response["choices"][0]["message"]
        content = message.get("content")
        # G3 修复：gate_set 修正推同样原样透传 tool_calls
        tool_calls = message.get("tool_calls")
        # 出结果后 unpark（一次性令牌）
        self.gate_park.unpark(context_id)
        return InferenceResult(
            context_id=context_id,
            content=content,
            result_ref=None,
            ext={"model": effective_model, "usage": response.get("usage"), "gate": "auto"},
            tool_calls=tool_calls,
        )
