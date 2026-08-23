# -*- coding: utf-8 -*-
"""sl ↔ ck/pk 内核适配层（_b P4，组件形态）

职责（DESIGN §七 Phase 4 任务 4.2 / 4.4）：
- 为 vendored ck 提供三端口适配器（ContextSource / DataPlane / LlmProvider）
- 为 pk 提供四缝填缝（推理缝经 SlContextKernel.infer）
- SlContextKernel(ContextKernel) 覆写 infer（pk 填缝方）——**不改 vendored ck 源码**（纯副本原则）

Phase 4 目标 = "适配层可装配 + ck infer 填缝验证"，用同步 mock 验证链路；
真实 sl Session（ContextSource 写面）/ 真实 downstream_llm（async 桥接）在 Phase 5 接入。

同步/异步鸿沟说明：ck 内核为同步（`_assemble_and_gate` 同步调 `llm_provider.chat`），
sl `DownstreamLLM` 为 async。P4 先以同步 mock 验证 infer 链路；async 桥接
（awaitable 包装 / 事件循环）在 Phase 5 处理。
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from .gate_manager import inject_kernels

# ── vendored ck ──
from ..kernels.context_kernel import ContextKernel, ContextPatch
from ..kernels.context_kernel.core.models import (
    GateMode, InferenceResult, SessionView,
)
from ..kernels.context_kernel.ports import ContextSource, DataPlane, LlmProvider

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════
# ContextSource 适配器（读 sl Session 只读视图）
# ═══════════════════════════════════════════════════════════

class SlContextSource:
    """ck ContextSource 适配器：读 sl Session 产出 SessionView（只读，红线⑥）。

    P4：从传入的内存源读取（Phase 5 接真实 sl SessionManager）。
    """

    def __init__(self, session_reader: Optional[Any] = None):
        # session_reader：可调用 read_session(session_id) -> SessionView 的对象
        self._reader = session_reader
        self._mem: dict[str, SessionView] = {}

    def register_session(self, session_id: str, view: SessionView) -> None:
        """P4 占位：注册内存会话视图（Phase 5 改用真实 sl Session）"""
        self._mem[session_id] = view

    def read_session(self, session_id: str) -> SessionView:
        if self._reader is not None and session_id in getattr(self._reader, "sessions", {}):
            return self._reader.read_session(session_id)
        return self._mem.get(session_id, SessionView())


# ═══════════════════════════════════════════════════════════
# DataPlane 适配器（适配 pk ArtifactStore）
# ═══════════════════════════════════════════════════════════

class SlDataPlane:
    """ck DataPlane 适配器：适配 pk ArtifactStore（数据面）。

    P4：内存占位；Phase 5 接 pk ArtifactStore（phase_kernel.ports.ArtifactStore）。
    """

    def __init__(self, backend: Optional[Any] = None):
        self._backend = backend
        self._mem: dict[str, Any] = {}

    def store(self, pipeline_id: str, ref: str, data: Any) -> Any:
        self._mem[f"{pipeline_id}:{ref}"] = data
        return {"ref": ref, "stored": True}

    def fetch(self, ref: str) -> dict[str, Any]:
        for k, v in self._mem.items():
            if k.endswith(":" + ref):
                return {"ref": ref, "data": v}
        return {}

    def transfer(self, pipeline_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        ref = payload.get("ref")
        data = payload.get("data")
        if ref is not None:
            self.store(pipeline_id, ref, data)
            return {"ref": ref, "transferred": True}
        return {}


# ═══════════════════════════════════════════════════════════
# LlmProvider 适配器（P4 同步 mock 封装；Phase 5 处理 async 桥接）
# ═══════════════════════════════════════════════════════════

class SlLlmProvider:
    """ck LlmProvider 适配器。

    P4：包装一个同步可调用（callable: (messages, model) -> content str），
    验证 infer 链路。Phase 5 改为桥接 sl DownstreamLLM（async），
    或经 ck run_openai 的异步路径。
    """

    def __init__(self, sync_call: Optional[Any] = None):
        self._sync_call = sync_call  # callable(messages, model) -> content
        self._reply: Optional[str] = None

    def set_reply(self, content: str) -> None:
        """P4 测试占位：固定回显 content（不真正调 LLM）"""
        self._reply = content

    def chat(self, messages, model, stream=False, service_name=None):
        if self._reply is not None:
            return {"choices": [{"message": {"content": self._reply}}]}
        if self._sync_call is not None:
            content = self._sync_call(messages, model)
            return {"choices": [{"message": {"content": content}}]}
        raise RuntimeError("SlLlmProvider: P4 需 set_reply 或注入 sync_call")


# ═══════════════════════════════════════════════════════════
# SlContextKernel：覆写 infer（pk 填缝方）——不改 vendored ck
# ═══════════════════════════════════════════════════════════

class SlContextKernel(ContextKernel):
    """组件形态 pk 填缝：在 sl 层覆写 ContextKernel.infer。

    vendored ck 基类 `infer` 保持 NotImplementedError（纯副本原则）；
    本子类在 sl 层实现 pk 推理缝契约。
    """

    def infer(self, context_patch: Any) -> Any:
        patch = context_patch
        ext = getattr(patch, "ext", None) or {}
        routing = ext.get("routing")
        intent = getattr(patch, "intent", None)
        context_id = getattr(patch, "context_id", None)
        session_id = context_id or ""

        session_view = self.context_source.read_session(session_id)
        return self._assemble_and_gate(
            session_view=session_view,
            current_user_content=intent,
            session_id=session_id,
            routing=routing,
            ext=ext,
            gate_mode=GateMode.CLOSED,  # pk 填缝需 content 回填 → closed 直推
            model=None,
            stream=False,
        )


# ═══════════════════════════════════════════════════════════
# 装配：构建 sl 侧 ck 内核 + 注入 gate_manager
# ═══════════════════════════════════════════════════════════

def build_sl_context_kernel(
    primary_model: str = "gpt-4o-mini",
    fallback_model: str = "gpt-4o-mini",
    llm_reply: Optional[str] = None,
) -> SlContextKernel:
    """构建 sl 侧 ck 内核（P4：mock 装配，Phase 5 接真实 sl Session + downstream_llm）"""
    source = SlContextSource()
    plane = SlDataPlane()
    provider = SlLlmProvider()
    if llm_reply:
        provider.set_reply(llm_reply)
    kernel = SlContextKernel(
        context_source=source,
        data_plane=plane,
        llm_provider=provider,
        primary_model=primary_model,
        fallback_model=fallback_model,
    )
    return kernel


def wire_gate_manager(kernel: SlContextKernel) -> None:
    """Phase 4：把 ck/pk 适配器注入 gate_manager（P3 的 inject_kernels）"""
    inject_kernels(ck=_CkGateAdapter(kernel), pk=_PkGateAdapter())


# gate_manager 的 ck/pk 端口适配（组件形态）

class _CkGateAdapter:
    """ck → CkGatePort：gate_manager 调 ck 内核（peek/amend/set_gate_mode）"""

    def __init__(self, kernel: ContextKernel):
        self._kernel = kernel

    def peek(self, context_id: str) -> Any:
        return self._kernel.gate_get(context_id)

    def amend(self, context_id: str, custom: Any) -> Any:
        return self._kernel.gate_set(context_id, custom)

    def set_gate_mode(self, mode: str) -> Any:
        return self._kernel.set_gate_mode(mode)


class _PkGateAdapter:
    """pk → PkGatePort：gate_manager 调 pk GateExecutor（Phase 5 接真实 pk）"""

    def query(self, session: Any, phase_path: Optional[list] = None) -> dict:
        return {"phase_path": phase_path, "status": "awaiting_approval",
                "pending_gate": "human_approval", "available_actions": ["confirm", "reject"]}

    def approve(self, session: Any, phase: Any) -> Any:
        return {"verdict": "approve"}

    def retry(self, session: Any, phase: Any, feedback: str) -> Any:
        return {"verdict": "retry", "feedback": feedback}

    def abort_tree(self, session: Any) -> Any:
        return {"verdict": "abort_tree"}

    def evaluate_quality(self, session: Any, phase: Any,
                         execution_passed: bool, detail: str) -> Any:
        return {"passed": execution_passed, "detail": detail}
