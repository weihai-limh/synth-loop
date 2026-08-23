# -*- coding: utf-8 -*-
"""sl ↔ ck/pk 内核适配层（_b P4→P5，组件形态）

职责（DESIGN §七 Phase 4 任务 4.2 / 4.4 + Phase 5 任务 5.3）：
- 为 vendored ck 提供三端口适配器（ContextSource / DataPlane / LlmProvider）
- SlContextKernel 作 ck 组件实例（**不改 vendored ck 源码**，纯副本原则）
- 为 pk 提供四缝填缝：推理缝归 `SlInferenceSeam`（services/inference_seam.py，
  暴露到 build_messages）；装配 `PhaseReasoningEngine`（build_phase_engine，P5.3 整体替换）
- gate_manager 的 ck/pk 端口适配（_CkGateAdapter / _PkGateAdapter）

P4：SlContextKernel 曾覆写 infer（同步 mock 验证）；P5 语义收敛——推理缝归
SlInferenceSeam（async，经 build_messages 收束 + ck 闸监听），SlContextKernel
不再覆写 infer（防腐败）。

同步/异步鸿沟化解：推理缝暴露到 sl build_messages（async），经 ck build_prompt
纯函数（sync 拼装）+ sl_llm_provider（async 推理），不再依赖 ck sync 直推链路。
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from .gate_manager import inject_kernels
from .inference_seam import SlInferenceSeam

# ── vendored ck ──
from ..kernels.context_kernel import ContextKernel, ContextPatch
from ..kernels.context_kernel.core.models import (
    GateMode, InferenceResult, SessionView,
)
from ..kernels.context_kernel.ports import ContextSource, DataPlane, LlmProvider

# ── vendored pk ──
from ..kernels.phase_kernel import (
    PhaseReasoningEngine,
    MechanicalPlanner, LocalExecutor, InMemoryArtifactStore,
)

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
# SlContextKernel：ck 组件实例（P5 语义收敛——推理缝归 SlInferenceSeam）
# ═══════════════════════════════════════════════════════════

class SlContextKernel(ContextKernel):
    """sl 侧 ck 组件实例（作为 gate_manager / 适配器用的 ck 内核）。

    P5 语义收敛（防腐败）：推理缝（pk 填缝）归 `SlInferenceSeam`（services/inference_seam.py），
    **不再**在 SlContextKernel 覆写 infer——基类 `infer` 保持 NotImplementedError
    （vendored ck 纯副本原则）。SlContextKernel 仅作 ck 组件实例供 `_CkGateAdapter`
    / build_messages 取会话快照用。
    """


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


# ═══════════════════════════════════════════════════════════
# P5.3 装配：pk PhaseReasoningEngine（四缝 + 推理缝=SlInferenceSeam）
# ═══════════════════════════════════════════════════════════

def build_phase_engine(
    context_source: Any,
    gate_manager: Optional[Any] = None,
    sl_llm_provider: Optional[Any] = None,
    max_phase_depth: int = 4,
    degraded_mode: bool = False,
) -> PhaseReasoningEngine:
    """装配 pk `PhaseReasoningEngine`（整体替换 sl 相位自持实现，P5.3）。

    四缝填缝：
    - planner：`MechanicalPlanner`（零 LLM 兜底；推理缝注入时 pk 优先走 seam 规划）
    - executor：`LocalExecutor`（进程内执行，mock 兼容；Phase 5 阶段）
    - inference_seam：`SlInferenceSeam`（推理缝暴露到 build_messages，经 ck 闸监听）
    - artifact_store：`InMemoryArtifactStore`（数据面）
    - store/gate：缺省（内存 _sessions + MechanicalGate）
    """
    seam = SlInferenceSeam(
        context_source=context_source,
        llm_provider=sl_llm_provider,
        gate_manager=gate_manager,
    )
    engine = PhaseReasoningEngine(
        executor=LocalExecutor(),
        planner=MechanicalPlanner(),
        artifact_store=InMemoryArtifactStore(),
        inference_seam=seam,
        degraded_mode=degraded_mode,
        max_phase_depth=max_phase_depth,
    )
    return engine
