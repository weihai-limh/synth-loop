"""Phase 4 T1/T2/T3/T6: Pipeline 完整模型测试 (v0_1_2)"""

import pytest
from app.models.pipeline import (
    PipelineSession, PlanConfig, PhaseConfig, PhaseDefinition,
    PhaseGates, PhaseHistory, QualityGate, AsyncTask, Artifact,
    PipelineGates, PipelineStatus, PhaseStatus,
)
from app.services.pipeline_lifecycle import PipelineLifecycleManager
from app.services.phase_executor import PhaseExecutor
from app.services.plan_compiler import PlanCompiler


class TestPipelineSessionModel:
    """T1: PipelineSession 数据模型"""

    def test_create_and_serialize(self):
        """创建 + 序列化/反序列化正确"""
        plan_config = PlanConfig(phases=[
            PhaseConfig(index=0, name="分析", description="需求分析", mode="single_ai",
                         gates=PhaseGates()),
        ])
        session = PipelineSession(
            intent="test intent",
            plan_config=plan_config,
        )
        d = session.to_dict()
        assert d["status"] == "draft"
        assert d["intent"] == "test intent"
        assert d["pipeline_id"] is not None

        # 反序列化
        s2 = PipelineSession.from_dict(d)
        assert s2.status == PipelineStatus.DRAFT
        assert s2.intent == "test intent"
        assert s2.pipeline_id == session.pipeline_id

    def test_t11_preburied_fields(self):
        """T11: V0.1.3 预埋字段注册不激活"""
        session = PipelineSession(intent="test", plan_config=PlanConfig(phases=[]))
        assert session.waiting_human_authorization is None
        assert session.physical_safety_check is None
        assert session.cost_tracking is None

    def test_phase_status_enum(self):
        assert PhaseStatus.PENDING.value == "pending"
        assert PhaseStatus.AWAITING_PATH_CONFIRM.value == "awaiting_path_confirm"
        assert PhaseStatus.AWAITING_APPROVAL.value == "awaiting_approval"

    def test_pipeline_status_enum(self):
        assert PipelineStatus.DRAFT.value == "draft"
        assert PipelineStatus.ACTIVE.value == "active"
        assert PipelineStatus.PAUSED.value == "paused"


class TestPipelineLifecycle:
    """T2: 管道生命周期状态机"""

    @pytest.fixture
    def manager(self):
        return PipelineLifecycleManager()

    @pytest.fixture
    def plan_config(self):
        return PlanConfig(phases=[
            PhaseConfig(index=0, name="Phase 1", description="First phase", mode="single_ai",
                         gates=PhaseGates()),
        ])

    @pytest.mark.asyncio
    async def test_full_lifecycle(self, manager, plan_config):
        """draft → active → paused → active → completed 完整往返"""
        session = await manager.create_pipeline("test", plan_config)
        assert session.status == PipelineStatus.DRAFT

        session = await manager.start(session)
        assert session.status == PipelineStatus.ACTIVE

        session = await manager.pause(session, "need review")
        assert session.status == PipelineStatus.PAUSED

        session = await manager.resume(session)
        assert session.status == PipelineStatus.ACTIVE

        session = await manager.complete(session)
        assert session.status == PipelineStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_draft_to_abort(self, manager, plan_config):
        """draft → aborted"""
        session = await manager.create_pipeline("test", plan_config)
        session = await manager.abort(session)
        assert session.status == PipelineStatus.ABORTED

    @pytest.mark.asyncio
    async def test_cannot_pause_from_draft(self, manager, plan_config):
        """draft 状态不能暂停"""
        session = await manager.create_pipeline("test", plan_config)
        with pytest.raises(ValueError):
            await manager.pause(session)

    @pytest.mark.asyncio
    async def test_cannot_complete_from_draft(self, manager, plan_config):
        """draft 状态不能完成"""
        session = await manager.create_pipeline("test", plan_config)
        with pytest.raises(ValueError):
            await manager.complete(session)


class TestPhaseStateMachine:
    """T3: 相位三闸状态机"""

    @pytest.fixture
    def executor(self):
        return PhaseExecutor()

    @pytest.fixture
    def pipeline_with_phases(self):
        plan_config = PlanConfig(phases=[
            PhaseConfig(index=0, name="Phase 1", description="test", mode="single_ai",
                         gates=PhaseGates(show_terminal=True, allow_path_edit=True,
                                          require_human_approval=True)),
        ])
        session = PipelineSession(intent="test", plan_config=plan_config)
        session.phases = [
            PhaseDefinition(index=0, name="Phase 1", description="test",
                            mode="single_ai",
                            gates=PhaseGates(show_terminal=True, allow_path_edit=True,
                                             require_human_approval=True)),
        ]
        session.status = PipelineStatus.ACTIVE
        return session

    @pytest.mark.asyncio
    async def test_gate2_awaiting_path_confirm(self, executor, pipeline_with_phases):
        """闸2 ON → pending 停留直到 path-confirm"""
        phase = await executor.start_phase(pipeline_with_phases)
        assert phase is not None
        assert phase.status == PhaseStatus.AWAITING_PATH_CONFIRM

    @pytest.mark.asyncio
    async def test_gate2_path_confirm_to_running(self, executor, pipeline_with_phases):
        """闸2 确认后 → running"""
        pipeline_with_phases.phases[0].status = PhaseStatus.AWAITING_PATH_CONFIRM
        phase = await executor.confirm_path(pipeline_with_phases, 0)
        assert phase.status == PhaseStatus.RUNNING

    @pytest.mark.asyncio
    async def test_gate3_awaiting_approval(self, executor, pipeline_with_phases):
        """quality_gate passed 后 → awaiting_approval"""
        status = await executor.evaluate_quality_gate(pipeline_with_phases, 0, True, "ok")
        assert status == PhaseStatus.AWAITING_APPROVAL
        assert pipeline_with_phases.phases[0].status == PhaseStatus.AWAITING_APPROVAL

    @pytest.mark.asyncio
    async def test_quality_gate_failed(self, executor, pipeline_with_phases):
        """execution_result failed → phase failed"""
        status = await executor.evaluate_quality_gate(pipeline_with_phases, 0, False, "error")
        assert status == PhaseStatus.FAILED
        assert pipeline_with_phases.phases[0].status == PhaseStatus.FAILED
        assert len(pipeline_with_phases.quality_gates) == 1

    @pytest.mark.asyncio
    async def test_reject_with_feedback(self, executor, pipeline_with_phases):
        """驳回 → running（反馈注入）"""
        pipeline_with_phases.phases[0].status = PhaseStatus.AWAITING_APPROVAL
        phase = await executor.reject_phase(pipeline_with_phases, 0, "needs more detail")
        assert phase.status == PhaseStatus.RUNNING

    @pytest.mark.asyncio
    async def test_approve(self, executor, pipeline_with_phases):
        """审批通过 → completed"""
        pipeline_with_phases.phases[0].status = PhaseStatus.AWAITING_APPROVAL
        phase = await executor.approve_phase(pipeline_with_phases, 0)
        assert phase.status == PhaseStatus.COMPLETED


class TestPlanCompiler:
    """T6: 计划编译器"""

    @pytest.fixture
    def compiler(self):
        return PlanCompiler()

    @pytest.fixture
    def plan_config_3_phases(self):
        return PlanConfig(phases=[
            PhaseConfig(index=0, name="需求分析", description="分析需求",
                         mode="single_ai", gates=PhaseGates()),
            PhaseConfig(index=1, name="方案设计", description="设计方案",
                         mode="single_ai_human_review",
                         gates=PhaseGates(allow_path_edit=True)),
            PhaseConfig(index=2, name="代码实现", description="写代码",
                         mode="single_ai", gates=PhaseGates(require_human_approval=True)),
        ])

    @pytest.mark.asyncio
    async def test_compile_3_phases(self, compiler, plan_config_3_phases):
        """3 相位 → 产物 phases 数组长度 3"""
        result = await compiler.compile(plan_config_3_phases)
        assert len(result["phases"]) == 3
        assert result["_mode"] == "direct"
        assert result["_schema"] == "text-cli-path-v1"

    @pytest.mark.asyncio
    async def test_edit_mode(self, compiler, plan_config_3_phases):
        """编辑模式 → _mode=edit"""
        result = await compiler.compile(plan_config_3_phases, mode="edit")
        assert result["_mode"] == "edit"
        assert "_schema" not in result
        assert len(result["phases"]) == 3

    @pytest.mark.asyncio
    async def test_empty_plan(self, compiler):
        """空 plan_config → phases 为空数组"""
        config = PlanConfig(phases=[])
        result = await compiler.compile(config)
        assert result["phases"] == []

    @pytest.mark.asyncio
    async def test_gate_schema_in_output(self, compiler, plan_config_3_phases):
        """闸门配置正确映射到输出"""
        result = await compiler.compile(plan_config_3_phases)
        p1 = result["phases"][1]  # Phase 2: allow_path_edit=True
        assert p1["gates"]["allow_path_edit"] is True

        p2 = result["phases"][2]  # Phase 3: require_human_approval=True
        assert p2["gates"]["require_human_approval"] is True
