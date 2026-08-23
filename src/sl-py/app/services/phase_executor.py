"""相位状态机——三闸驱动 (v0_1_2 T3)

闸1 show_terminal: 推仪表盘
闸2 allow_path_edit: 路径确认
闸3 require_human_approval: 人工审批
"""

import logging
from datetime import datetime
from typing import Optional

from ..models.pipeline import (
    PipelineSession, PhaseStatus, PhaseDefinition,
    PhaseGates, QualityGate, GateType, GateResult,
)

logger = logging.getLogger(__name__)


class PhaseExecutor:
    """相位执行器——三闸状态机"""

    async def start_phase(self, session: PipelineSession) -> Optional[PhaseDefinition]:
        """开始执行下一个待处理相位"""
        current = session.get_current_phase()
        if current is None:
            return None

        # 闸2: allow_path_edit → 等待路径确认
        if current.gates.allow_path_edit:
            current.status = PhaseStatus.AWAITING_PATH_CONFIRM
            session.updated_at = datetime.now()
            logger.info(f"Phase {current.index}: awaiting path confirm (gate 2)")
            return current

        # 闸2 OFF → 直接进 running
        current.status = PhaseStatus.RUNNING
        session.updated_at = datetime.now()
        session.advance_phase(current.index, PhaseStatus.RUNNING)
        logger.info(f"Phase {current.index}: started (gate 2 off)")
        return current

    async def confirm_path(self, session: PipelineSession, phase_index: int,
                            confirmed: bool = True, edits: Optional[dict] = None) -> PhaseDefinition:
        """闸2: 确认路径 JSON → 进 running"""
        if phase_index >= len(session.phases):
            raise IndexError(f"Phase {phase_index} out of range")

        phase = session.phases[phase_index]
        if phase.status != PhaseStatus.AWAITING_PATH_CONFIRM:
            raise ValueError(f"Phase {phase_index} is not awaiting path confirm (status={phase.status})")

        if not confirmed:
            phase.status = PhaseStatus.FAILED
            session.updated_at = datetime.now()
            return phase

        # 路径确认 → running
        phase.status = PhaseStatus.RUNNING
        session.updated_at = datetime.now()
        session.advance_phase(phase_index, PhaseStatus.RUNNING)
        logger.info(f"Phase {phase_index}: path confirmed, entering running")
        return phase

    async def evaluate_quality_gate(self, session: PipelineSession, phase_index: int,
                                     execution_passed: bool, detail: str = "") -> PhaseStatus:
        """评估 execution_result 质量栅

        执行完成后先评估 → passed? 检查闸3 / failed? 相位 failed
        """
        gate_type = GateType.EXECUTION_RESULT.value
        result = GateResult.PASSED.value if execution_passed else GateResult.FAILED.value
        session.add_quality_gate(phase_index, gate_type, result, detail)

        if not execution_passed:
            session.phases[phase_index].status = PhaseStatus.FAILED
            session.updated_at = datetime.now()
            logger.warning(f"Phase {phase_index}: quality gate failed: {detail}")
            return PhaseStatus.FAILED

        # 闸3: require_human_approval → 等待审批
        phase = session.phases[phase_index]
        if phase.gates.require_human_approval:
            phase.status = PhaseStatus.AWAITING_APPROVAL
            session.updated_at = datetime.now()
            logger.info(f"Phase {phase_index}: awaiting human approval (gate 3)")
            return PhaseStatus.AWAITING_APPROVAL

        # 无闸3 → 直接完成
        phase.status = PhaseStatus.COMPLETED
        session.advance_phase(phase_index, PhaseStatus.COMPLETED,
                               output=f"Phase {phase_index} completed")
        logger.info(f"Phase {phase_index}: completed (gate 3 off)")
        return PhaseStatus.COMPLETED

    async def approve_phase(self, session: PipelineSession, phase_index: int) -> PhaseDefinition:
        """闸3: 审批通过 → completed"""
        if phase_index >= len(session.phases):
            raise IndexError(f"Phase {phase_index} out of range")

        phase = session.phases[phase_index]
        if phase.status != PhaseStatus.AWAITING_APPROVAL:
            raise ValueError(f"Phase {phase_index} is not awaiting approval (status={phase.status})")

        phase.status = PhaseStatus.COMPLETED
        session.add_quality_gate(phase_index, GateType.HUMAN_REVIEW.value,
                                  GateResult.PASSED.value, "approved by human")
        session.advance_phase(phase_index, PhaseStatus.COMPLETED,
                               output=f"Phase {phase_index} approved")
        logger.info(f"Phase {phase_index}: approved")
        return phase

    async def reject_phase(self, session: PipelineSession, phase_index: int,
                            feedback: str) -> PhaseDefinition:
        """闸3: 驳回 → running（重试，反馈注入下一轮）"""
        if phase_index >= len(session.phases):
            raise IndexError(f"Phase {phase_index} out of range")

        phase = session.phases[phase_index]
        if phase.status != PhaseStatus.AWAITING_APPROVAL:
            raise ValueError(f"Phase {phase_index} is not awaiting approval (status={phase.status})")

        phase.status = PhaseStatus.RUNNING
        session.add_quality_gate(phase_index, GateType.HUMAN_REVIEW.value,
                                  GateResult.FAILED.value, f"rejected: {feedback}")

        # 记录驳回反馈到 phase_history
        for h in session.phase_history:
            if h.index == phase_index:
                h.human_feedback = feedback
                break

        session.updated_at = datetime.now()
        logger.info(f"Phase {phase_index}: rejected with feedback: {feedback[:50]}")
        return phase
