"""管道生命周期管理 (v0_1_2 T2/T9)

T2: 管道状态机——draft→active→paused/completed/aborted
T9: 暂停/恢复/回退
"""

import logging
from datetime import datetime
from typing import Optional

from ..models.pipeline import (
    PipelineSession, PipelineStatus, PhaseStatus,
    PlanConfig, PipelineGates, PhaseGates,
)

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════
# T2: 管道状态机
# ═══════════════════════════════════════════════════════════

ALLOWED_TRANSITIONS = {
    PipelineStatus.DRAFT: {PipelineStatus.ACTIVE, PipelineStatus.ABORTED},
    PipelineStatus.ACTIVE: {PipelineStatus.PAUSED, PipelineStatus.COMPLETED, PipelineStatus.ABORTED},
    PipelineStatus.PAUSED: {PipelineStatus.ACTIVE, PipelineStatus.ABORTED},
    PipelineStatus.COMPLETED: set(),  # 终态
    PipelineStatus.ABORTED: set(),    # 终态
}


class PipelineLifecycleManager:
    """管道生命周期管理器"""

    async def create_pipeline(self, intent: str, plan_config: PlanConfig,
                               user_id: Optional[str] = None,
                               pipeline_gates: Optional[PipelineGates] = None) -> PipelineSession:
        """创建管道（status=draft）"""
        session = PipelineSession(
            intent=intent,
            plan_config=plan_config,
            user_id=user_id,
            pipeline_gates=pipeline_gates or PipelineGates(),
        )
        logger.info(f"Pipeline created: {session.pipeline_id}, status=draft")
        return session

    async def confirm_plan(self, session: PipelineSession) -> PipelineSession:
        """确认计划（管道级闸1）"""
        if session.status != PipelineStatus.DRAFT:
            raise ValueError(f"Cannot confirm_plan: pipeline is {session.status}")
        # 门控逻辑：若 confirm_plan=true，标记已确认
        # 后续 start() 检查双门状态
        session.confirm_plan()
        logger.info(f"Pipeline {session.pipeline_id}: plan confirmed")
        return session

    async def start(self, session: PipelineSession) -> PipelineSession:
        """启动管道（管道级闸2）

        双门控制：
        - confirm_plan=true 且未调 confirm_plan → 阻塞
        - confirm_start=true 且未调 start → 阻塞
        - 双门全 OFF → 直接进 active
        """
        if session.status != PipelineStatus.DRAFT:
            raise ValueError(f"Cannot start: pipeline is {session.status}")

        session.start()
        logger.info(f"Pipeline {session.pipeline_id}: started, {len(session.phases)} phases")
        return session

    async def pause(self, session: PipelineSession, reason: str = "") -> PipelineSession:
        """暂停管道"""
        if session.status != PipelineStatus.ACTIVE:
            raise ValueError(f"Cannot pause from status: {session.status}")
        session.pause(reason)
        logger.info(f"Pipeline {session.pipeline_id}: paused (reason: {reason})")
        return session

    async def resume(self, session: PipelineSession) -> PipelineSession:
        """恢复管道"""
        if session.status != PipelineStatus.PAUSED:
            raise ValueError(f"Cannot resume from status: {session.status}")
        session.resume()
        logger.info(f"Pipeline {session.pipeline_id}: resumed")
        return session

    async def abort(self, session: PipelineSession, reason: str = "") -> PipelineSession:
        """中止管道"""
        if session.status in {PipelineStatus.COMPLETED, PipelineStatus.ABORTED}:
            raise ValueError(f"Cannot abort from terminal status: {session.status}")
        session.abort(reason)
        logger.info(f"Pipeline {session.pipeline_id}: aborted (reason: {reason})")
        return session

    async def complete(self, session: PipelineSession) -> PipelineSession:
        """完成管道"""
        if session.status != PipelineStatus.ACTIVE:
            raise ValueError(f"Cannot complete from status: {session.status}")
        session.complete()
        logger.info(f"Pipeline {session.pipeline_id}: completed")
        return session

    def get_allowed_actions(self, session: PipelineSession) -> set[PipelineStatus]:
        """获取当前状态允许的转换目标"""
        return ALLOWED_TRANSITIONS.get(session.status, set())

    # ═══════════════════════════════════════════════════════════
    # T9: 暂停/恢复/回退
    # ═══════════════════════════════════════════════════════════

    async def rollback_and_recompile(self, session: PipelineSession,
                                      from_phase_index: int,
                                      new_plan_config: PlanConfig) -> PipelineSession:
        """回退重做——修改 plan_config 后从指定相位重新开始

        操作：
        1. invalidate 指定相位及之后的所有 phase_history（标记 reverted）
        2. 重置 phases 状态
        3. 重编译 plan_config
        """
        if session.status != PipelineStatus.PAUSED:
            raise ValueError(f"Cannot rollback from status: {session.status}")

        # invalidate 相位历史
        for h in session.phase_history:
            if h.index >= from_phase_index:
                h.reverted_at = datetime.now()

        # 重置 from_phase_index 及之后的相位状态
        for i in range(from_phase_index, len(session.phases)):
            session.phases[i].status = PhaseStatus.PENDING

        # 更新 plan_config（已重置相位状态，无需替换 phases 列表）
        session.plan_config = new_plan_config

        logger.info(f"Pipeline {session.pipeline_id}: rolled back to phase {from_phase_index}")
        return session
