# -*- coding: utf-8 -*-
"""统一闸管理 gate_manager（_b P3）——跨内核闸编排器（组件形态）

依据：`functional_design/gate-manager_zh.md` + `concept_V0_1_2_b §五之二 P3 / 主线 E`

形态（用户拍板）：**组件形态**——内部直接调 ck/pk 内核方法（import 内核），
**非 HTTP 代理**（vendored 铁律，concept §0.2）。HTTP 钩子面仅作对外暴露，
供 sl 之外的外挂改进服务消费；sl 内部不拥有学习环。

P3 阶段适配器用 Protocol + mock（Phase 4 vendored 后注入真实 ck/pk）：
- CkGatePort  → 对应 ck `ContextKernel.gate_get/gate_set/set_gate_mode`
- PkGatePort  → 对应 pk `PhaseGateExecutor.approve_phase/retry_phase/abort_tree/evaluate_quality_gate`

闸统一抽象（gate_type 五类）：
- decision：决策点确认（管道/相位推进，归 pk）
- approval：相位结果审批（pk 人闸）
- quality：执行结果质量（pk 质量闸）
- intervention：上下文干预（ck 推理闸，推模型前）
- meta：ck 闸本身开关（转发 ck set_gate_mode）
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from enum import Enum
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════
# 闸统一抽象
# ═══════════════════════════════════════════════════════════

class GateType(str, Enum):
    """闸类型（统一抽象，五类）"""
    DECISION = "decision"          # 决策点确认（管道/相位推进）
    APPROVAL = "approval"          # 相位结果审批
    QUALITY = "quality"            # 执行结果质量
    INTERVENTION = "intervention"  # 上下文干预（推模型前）
    META = "meta"                  # ck 闸本身开关


class GateResponse:
    """闸响应（统一语义）"""
    def __init__(self, gate_type: str, verdict: str, data: Any = None,
                 reason: str = ""):
        self.gate_type = gate_type
        self.verdict = verdict      # confirm/reject/amend/retry/abort/unpark/on/off/auto/pass/fail
        self.data = data
        self.reason = reason

    def to_dict(self) -> dict:
        return {"gate_type": self.gate_type, "verdict": self.verdict,
                "data": self.data, "reason": self.reason}


# ═══════════════════════════════════════════════════════════
# 适配器接口（组件形态，Phase 4 vendored 后注入真实 ck/pk）
# ═══════════════════════════════════════════════════════════

class CkGatePort(ABC):
    """ck 推理闸 + 元闸 适配器接口（组件形态，对应 ContextKernel）"""
    @abstractmethod
    def peek(self, context_id: str) -> Any:
        """推理闸 peek：取回 context 视图（对应 gate_get）"""
        ...

    @abstractmethod
    def amend(self, context_id: str, custom: Any) -> Any:
        """推理闸 amend：修正推 LLM（对应 gate_set，unpark 一次性）"""
        ...

    @abstractmethod
    def set_gate_mode(self, mode: str) -> Any:
        """元闸：控制 ck 推理闸本身开关（closed/auto，对应 set_gate_mode）"""
        ...


class PkGatePort(ABC):
    """pk 人闸 + 质量闸 适配器接口（组件形态，对应 PhaseGateExecutor）"""
    @abstractmethod
    def query(self, session: Any, phase_path: Optional[list] = None) -> dict:
        """人闸查询：查相位待闸状态（status/pending_gate/available_actions）"""
        ...

    @abstractmethod
    def approve(self, session: Any, phase: Any) -> Any:
        """人闸 approve：审批通过 → COMPLETED（对应 approve_phase）"""
        ...

    @abstractmethod
    def retry(self, session: Any, phase: Any, feedback: str) -> Any:
        """人闸 retry：驳回重跑当前相位（对应 retry_phase）"""
        ...

    @abstractmethod
    def abort_tree(self, session: Any) -> Any:
        """人闸 abort_tree：置整树 ABORTED（对应 abort_tree）"""
        ...

    @abstractmethod
    def evaluate_quality(self, session: Any, phase: Any,
                         execution_passed: bool, detail: str) -> Any:
        """质量闸：评估执行结果（对应 evaluate_quality_gate）"""
        ...


# ═══════════════════════════════════════════════════════════
# 预制闸组合函数注册表
# ═══════════════════════════════════════════════════════════

class GateCombo:
    """一种闸组合 = 一种响应模式"""
    def __init__(self, name: str, gates: list[GateType]):
        self.name = name
        self.gates = gates

    def to_dict(self) -> dict:
        return {"name": self.name, "gates": [g.value for g in self.gates]}


# 默认预制组合（gate-manager 设计稿 §四）
DEFAULT_COMBOS: dict[str, list[GateType]] = {
    "decision_only":        [GateType.DECISION],                        # 简单相位，无人工审批
    "decision_approval":    [GateType.DECISION, GateType.APPROVAL],     # 需人工把关
    "intervention_approval": [GateType.INTERVENTION, GateType.APPROVAL], # 敏感任务：上下文可改 + 结果审批
    "meta_all_on":          [GateType.META, GateType.INTERVENTION, GateType.APPROVAL],  # 复杂任务全链路
    "all_off":              [],                                          # 直推，最省
}


# ═══════════════════════════════════════════════════════════
# gate_manager 编排器
# ═══════════════════════════════════════════════════════════

class GateManager:
    """统一闸编排器——聚合 ck/pk 闸，持有预制组合函数注册表，跨内核循环。

    组件形态：内部调 ck/pk 内核（经 CkGatePort / PkGatePort）。
    P3 阶段适配器为 Protocol + mock；Phase 4 vendored 后注入真实 ck/pk。
    """

    def __init__(self, ck: Optional[CkGatePort] = None,
                 pk: Optional[PkGatePort] = None):
        self.ck = ck
        self.pk = pk
        self._combos: dict[str, list[GateType]] = dict(DEFAULT_COMBOS)
        self._active_combo: str = "all_off"
        self._cycle_stack: list[GateResponse] = []

    # ── 组合注册表 ──

    def register_combo(self, name: str, gates: list[GateType]) -> None:
        """注册预制闸组合函数（一种组合 = 一种响应模式）"""
        self._combos[name] = gates

    def set_active_combo(self, name: str) -> None:
        if name not in self._combos:
            raise ValueError(f"unknown combo: {name}")
        self._active_combo = name

    def get_combos(self) -> dict[str, list[str]]:
        return {k: [g.value for g in v] for k, v in self._combos.items()}

    def get_config(self) -> dict:
        return {"active_combo": self._active_combo,
                "combos": self.get_combos(),
                "meta_gate": self._meta_gate_state(),
                "ck_attached": self.ck is not None,
                "pk_attached": self.pk is not None}

    # ── meta 闸（ck 闸开关）──

    def _meta_gate_state(self) -> str:
        if self.ck is None:
            return "no_ck"
        # 读取当前 ck gate_mode（若支持）
        try:
            return self._meta_gate
        except AttributeError:
            return "closed"

    def set_meta_gate(self, mode: str) -> GateResponse:
        """元闸：控制 ck 推理闸本身开关（closed/auto/on/off）"""
        if self.ck is None:
            return GateResponse(GateType.META.value, "no_ck", reason="ck 适配器未注入")
        normalized = mode
        if mode == "on":
            normalized = "auto"
        elif mode == "off":
            normalized = "closed"
        if normalized not in ("closed", "auto"):
            return GateResponse(GateType.META.value, "invalid", reason=f"invalid meta gate mode: {mode}")
        self._meta_gate = normalized
        self.ck.set_gate_mode(normalized)
        logger.info(f"gate_manager meta gate -> {normalized}")
        return GateResponse(GateType.META.value, normalized)

    # ── 跨内核循环 ──

    def run_cycle(self, context_id: str = "", phase=None, session=None,
                  custom_context: Any = None) -> list[GateResponse]:
        """跨内核循环：入口 → 闸响应 → 再次请求 → 最终响应。

        按 active_combo 的门序列依次执行：
          meta → intervention(ck peek/amend) → decision → approval → quality
        返回各闸响应栈（最终响应为栈尾）。
        """
        self._cycle_stack = []
        combo = self._combos.get(self._active_combo, [])

        for gate in combo:
            if gate == GateType.META and self.ck is not None:
                self._cycle_stack.append(self._meta_apply())
            elif gate == GateType.INTERVENTION and self.ck is not None and context_id:
                self._cycle_stack.append(self._intervention_apply(context_id, custom_context))
            elif gate == GateType.APPROVAL and self.pk is not None and phase is not None:
                self._cycle_stack.append(self._approval_query(phase))
            elif gate == GateType.QUALITY and self.pk is not None and phase is not None:
                self._cycle_stack.append(self._quality_eval(phase))
            elif gate == GateType.DECISION:
                # 决策点确认由 pk 决策点状态机驱动（跨内核循环中查询待闸状态）
                self._cycle_stack.append(self._decision_query(phase))
        return self._cycle_stack

    def _meta_apply(self) -> GateResponse:
        """meta 闸：应用当前 meta 模式到 ck"""
        return GateResponse(GateType.META.value, "applied", data={"meta": self._meta_gate})

    def _intervention_apply(self, context_id: str, custom: Any) -> GateResponse:
        """intervention 闸：ck 推理闸 peek → (amend if custom) → unpark"""
        assert self.ck is not None
        peeked = self.ck.peek(context_id)
        if custom is not None:
            result = self.ck.amend(context_id, custom)
            return GateResponse(GateType.INTERVENTION.value, "unpark",
                                data={"peek": peeked, "result": result})
        return GateResponse(GateType.INTERVENTION.value, "peek", data=peeked)

    def _approval_query(self, phase) -> GateResponse:
        """approval 闸：查询相位待闸状态"""
        assert self.pk is not None
        pending = self.pk.query(None, phase_path=getattr(phase, "path", None)) if phase else {}
        return GateResponse(GateType.APPROVAL.value, "pending",
                            data=pending)

    def _quality_eval(self, phase) -> GateResponse:
        """quality 闸：评估相位执行结果（占位——真实评估由 pk evaluate_quality_gate 在 Phase 4 接）"""
        return GateResponse(GateType.QUALITY.value, "eval", data={"phase": getattr(phase, "name", None)})

    def _decision_query(self, phase) -> GateResponse:
        """decision 闸：查询决策点待确认状态（占位——pk 决策点状态机驱动）"""
        return GateResponse(GateType.DECISION.value, "query",
                            data={"step": getattr(phase, "status", None) if phase else None})


# ═══════════════════════════════════════════════════════════
# mock 适配器（P3 占位——Phase 4 vendored 后注入真实 ck/pk）
# ═══════════════════════════════════════════════════════════

class MockCkGatePort(CkGatePort):
    """mock ck 适配器：Phase 4 前占位，验证 gate_manager 编排可跑"""
    def __init__(self):
        self._mode = "closed"
        self._park: dict[str, Any] = {}

    def peek(self, context_id: str) -> Any:
        return self._park.get(context_id, {"context": "mock-context", "context_id": context_id})

    def amend(self, context_id: str, custom: Any) -> Any:
        return {"context_id": context_id, "content": "mock-amended", "custom": custom}

    def set_gate_mode(self, mode: str) -> Any:
        self._mode = mode
        return {"gate_mode": mode}


class MockPkGatePort(PkGatePort):
    """mock pk 适配器：Phase 4 前占位"""
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
# 全局实例（P3 阶段默认挂 mock 适配器，Phase 4 注入真实 ck/pk）
# ═══════════════════════════════════════════════════════════

_gate_manager: Optional[GateManager] = None


def get_gate_manager() -> GateManager:
    global _gate_manager
    if _gate_manager is None:
        _gate_manager = GateManager(ck=MockCkGatePort(), pk=MockPkGatePort())
    return _gate_manager


def inject_kernels(ck: CkGatePort, pk: PkGatePort) -> GateManager:
    """Phase 4 vendored 后注入真实 ck/pk 适配器（组件形态）"""
    global _gate_manager
    _gate_manager = GateManager(ck=ck, pk=pk)
    return _gate_manager
