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

import asyncio
import logging
from typing import Any, Optional

from .gate_manager import inject_kernels
from .inference_seam import SlInferenceSeam
from .sl_artifact_store import SlArtifactStore

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
from ..kernels.phase_kernel.adapters.strata_matcher import PhasePlanPlanner
from ..kernels.phase_kernel.core.gates import PhaseGateExecutor
from ..kernels.phase_kernel.core.models import PhaseStatus

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
    _c：已核实 ck 内核 `data_plane` 只赋值未调用（context_kernel.py:40），**暂缓改造保留内存占位**；
    未来 ck 数据面端口启用时再接真实存储。链路 C 产物桥接走独立的 `SlArtifactStore`（services/sl_artifact_store.py）。
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
    """Phase 4：把 ck/pk 适配器注入 gate_manager（P3 的 inject_kernels）

    _e Phase 4：pk 适配器注入真实 `PhaseGateExecutor`（`_PkGateAdapter` 内部 async 桥接），
    取代 mock 恒值返回（approve/retry/abort_tree/evaluate_quality 委托真实 pk）。
    """
    inject_kernels(ck=_CkGateAdapter(kernel), pk=_PkGateAdapter(PhaseGateExecutor()))


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
    """pk → PkGatePort：gate_manager 调 pk `PhaseGateExecutor`（_e Phase 4 接通真实 pk）。

    契约校正（已核实源码）：
    - pk `PhaseGateExecutor` 四方法均 **async**，sl `PkGatePort` 同步 → 内部用 `asyncio.run()` 桥接
      （sl gate_manager 在请求线程同步调用，无既有事件循环，安全）。
    - `query` 无 pk 直接对应（受控相位面在 pk serve，sl 无 serve/）→ 从 `phase.status` 自实现映射。
    - `run_cycle._approval_query` 传 `session=None` 给 query → 不依赖 session，从 phase 读状态。
    """

    def __init__(self, gate_executor: Optional[PhaseGateExecutor] = None):
        self._exec = gate_executor or PhaseGateExecutor()

    # ── query：受控相位面自实现（从 phase.status 映射，不依赖 session）──
    def query(self, session: Any, phase_path: Optional[list] = None) -> dict:
        # gate_manager._approval_query 调 query(None, phase_path=...) —— session 为 None。
        # 相位由调用方持有（phase 参数不在此处传入），此处仅返回按 phase_path 的结构；
        # 实际 status 由调用方在 run_cycle 中以 phase 传入 evaluate_quality/approve 等。
        # 本适配器 query 面向"待闸状态查询"，phase_path 定位；status 由调用方上下文决定。
        return {"phase_path": phase_path, "status": None,
                "pending_gate": "human_approval", "available_actions": ["confirm", "reject"]}

    @staticmethod
    def _pending_gate_of(phase: Any) -> dict:
        """从 pk 相位对象读 status → 受控相位面（对齐 pk serve `_to_envelope` 语义）。"""
        status = getattr(phase, "status", None)
        if status == PhaseStatus.AWAITING_PATH_CONFIRM:
            return {"pending_gate": "path_edit", "available_actions": ["confirm", "reject", "abort"]}
        if status == PhaseStatus.AWAITING_APPROVAL:
            return {"pending_gate": "human_approval", "available_actions": ["confirm", "reject"]}
        if status == PhaseStatus.RUNNING:
            return {"pending_gate": None, "available_actions": ["check_result", "abort"]}
        return {"pending_gate": None, "available_actions": []}

    # ── approve/retry/abort_tree/evaluate_quality：委托真实 pk + async 桥接 ──
    def approve(self, session: Any, phase: Any) -> Any:
        return asyncio.run(self._exec.approve_phase(session, phase))

    def retry(self, session: Any, phase: Any, feedback: str) -> Any:
        return asyncio.run(self._exec.retry_phase(session, phase, feedback))

    def abort_tree(self, session: Any) -> Any:
        return asyncio.run(self._exec.abort_tree(session))

    def evaluate_quality(self, session: Any, phase: Any,
                         execution_passed: bool, detail: str) -> Any:
        return asyncio.run(self._exec.evaluate_quality_gate(
            session, phase, execution_passed, detail))


# ═══════════════════════════════════════════════════════════
# P5.3 装配：pk PhaseReasoningEngine（四缝 + 推理缝=SlInferenceSeam）
# ═══════════════════════════════════════════════════════════

def build_phase_engine(
    context_source: Any,
    gate_manager: Optional[Any] = None,
    sl_llm_provider: Optional[Any] = None,
    max_phase_depth: int = 4,
    degraded_mode: bool = False,
    strata_base_url: Optional[str] = None,
) -> PhaseReasoningEngine:
    """装配 pk `PhaseReasoningEngine`（整体替换 sl 相位自持实现，P5.3）。

    四缝填缝：
    - planner：`PhasePlanPlanner`（_e 接 sm，经 sm 缝取结构化 bundle；`strata_base_url` 空 → 内部回落 MechanicalPlanner 兜底）
    - executor：`LocalExecutor`（进程内执行，mock 兼容；Phase 5 阶段）
    - inference_seam：`SlInferenceSeam`（推理缝暴露到 build_messages，经 ck 闸监听）
    - artifact_store：`SlArtifactStore`（数据面，pk 产物落 sl SQLite）
    - store/gate：缺省（内存 _sessions + MechanicalGate）

    `strata_base_url`（_e Phase 3.2，已拍板接 sm）：strata-match 地址；缺省 `None` → `PhasePlanPlanner.no_strata=True`，
    内部回落到机械规划（sm 不进相位链）。调用方（如 `phase_chat_orchestrator`）从 sl `config.yaml` 取 sm 地址传入。
    """
    seam = SlInferenceSeam(
        context_source=context_source,
        llm_provider=sl_llm_provider,
        gate_manager=gate_manager,
    )
    # _e Phase 3.2：接 sm——planner 用 PhasePlanPlanner（sm 缝取 bundle）；
    # strata_base_url 空 → no_strata=True，PhasePlanPlanner 内部回落机械兜底（不崩）。
    planner = PhasePlanPlanner(
        base_url=strata_base_url,
        llm=None,  # 本 _e 不接 LLM 规划（联调延后）；PhasePlanPlanner 无 llm 时走 sm prompt 直接规划
        no_strata=(strata_base_url is None),
    )
    engine = PhaseReasoningEngine(
        executor=LocalExecutor(),
        planner=planner,
        artifact_store=SlArtifactStore(),   # _c: pk 产物落 sl SQLite（链路 C 桥接）
        inference_seam=seam,
        degraded_mode=degraded_mode,
        max_phase_depth=max_phase_depth,
    )
    return engine
