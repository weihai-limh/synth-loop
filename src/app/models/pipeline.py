"""PipelineSession 数据模型 (v0_1_2 T1/T11)

T1: PipelineSession 核心模型——跨项目单一真相来源
T11: V0.1.3 字段预埋——注册不激活
"""

from datetime import datetime
from enum import Enum
from typing import Any, Optional
from uuid import uuid4


# ═══════════════════════════════════════════════════════════
# 枚举
# ═══════════════════════════════════════════════════════════

class PipelineStatus(str, Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    ABORTED = "aborted"


class PhaseStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    AWAITING_PATH_CONFIRM = "awaiting_path_confirm"
    AWAITING_APPROVAL = "awaiting_approval"
    COMPLETED = "completed"
    FAILED = "failed"


class PhaseMode(str, Enum):
    SINGLE_AI = "single_ai"
    SINGLE_AI_HUMAN_REVIEW = "single_ai_human_review"
    MULTI_AI_COMPARE = "multi_ai_compare"


class GateType(str, Enum):
    EXECUTION_RESULT = "execution_result"
    HUMAN_REVIEW = "human_review"
    LLM_SELF_CHECK = "llm_self_check"


class GateResult(str, Enum):
    PASSED = "passed"
    FAILED = "failed"
    PENDING = "pending"


# ═══════════════════════════════════════════════════════════
# 核心模型
# ═══════════════════════════════════════════════════════════

class PhaseGates:
    """相位三闸门配置"""
    def __init__(self, show_terminal: bool = True, allow_path_edit: bool = False,
                 require_human_approval: bool = False):
        self.show_terminal = show_terminal
        self.allow_path_edit = allow_path_edit
        self.require_human_approval = require_human_approval

    def to_dict(self) -> dict:
        return {
            "show_terminal": self.show_terminal,
            "allow_path_edit": self.allow_path_edit,
            "require_human_approval": self.require_human_approval,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "PhaseGates":
        return cls(
            show_terminal=data.get("show_terminal", True),
            allow_path_edit=data.get("allow_path_edit", False),
            require_human_approval=data.get("require_human_approval", False),
        )


class PhaseConfig:
    """相位配置（用户输入）"""
    def __init__(self, index: int, name: str, description: str, mode: str = "single_ai",
                 mode_params: Optional[dict] = None, gates: Optional[PhaseGates] = None):
        self.index = index
        self.name = name
        self.description = description
        self.mode = mode
        self.mode_params = mode_params
        self.gates = gates or PhaseGates()

    def to_dict(self) -> dict:
        return {
            "index": self.index, "name": self.name, "description": self.description,
            "mode": self.mode, "mode_params": self.mode_params,
            "gates": self.gates.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "PhaseConfig":
        return cls(
            index=data["index"], name=data["name"], description=data["description"],
            mode=data.get("mode", "single_ai"), mode_params=data.get("mode_params"),
            gates=PhaseGates.from_dict(data.get("gates", {})),
        )


class PlanConfig:
    """计划配置"""
    def __init__(self, phases: list[PhaseConfig]):
        self.phases = phases

    def to_dict(self) -> dict:
        return {"phases": [p.to_dict() for p in self.phases]}

    @classmethod
    def from_dict(cls, data: dict) -> "PlanConfig":
        return cls(phases=[PhaseConfig.from_dict(p) for p in data.get("phases", [])])


class PhaseDefinition:
    """相位定义（运行时）"""
    def __init__(self, index: int, name: str, description: str, mode: str = "single_ai",
                 mode_params: Optional[dict] = None, gates: Optional[PhaseGates] = None,
                 status: PhaseStatus = PhaseStatus.PENDING):
        self.index = index
        self.name = name
        self.description = description
        self.mode = mode
        self.mode_params = mode_params
        self.gates = gates or PhaseGates()
        self.status = status

    def to_dict(self) -> dict:
        return {
            "index": self.index, "name": self.name, "description": self.description,
            "mode": self.mode, "mode_params": self.mode_params,
            "gates": self.gates.to_dict(), "status": self.status.value,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "PhaseDefinition":
        return cls(
            index=data["index"], name=data["name"], description=data["description"],
            mode=data.get("mode", "single_ai"), mode_params=data.get("mode_params"),
            gates=PhaseGates.from_dict(data.get("gates", {})),
            status=PhaseStatus(data.get("status", "pending")),
        )


class PhaseHistory:
    """相位执行历史"""
    def __init__(self, index: int, status: PhaseStatus, output: Optional[str] = None,
                 path_json: Optional[dict] = None, human_feedback: Optional[str] = None,
                 gates: Optional[PhaseGates] = None, started_at: Optional[datetime] = None,
                 completed_at: Optional[datetime] = None, reverted_at: Optional[datetime] = None):
        self.index = index
        self.status = status
        self.output = output
        self.path_json = path_json
        self.human_feedback = human_feedback
        self.gates = gates or PhaseGates()
        self.started_at = started_at
        self.completed_at = completed_at
        self.reverted_at = reverted_at

    def to_dict(self) -> dict:
        return {
            "index": self.index, "status": self.status.value,
            "output": self.output, "path_json": self.path_json,
            "human_feedback": self.human_feedback,
            "gates": self.gates.to_dict(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "reverted_at": self.reverted_at.isoformat() if self.reverted_at else None,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "PhaseHistory":
        return cls(
            index=data["index"], status=PhaseStatus(data["status"]),
            output=data.get("output"), path_json=data.get("path_json"),
            human_feedback=data.get("human_feedback"),
            gates=PhaseGates.from_dict(data.get("gates", {})),
            started_at=datetime.fromisoformat(data["started_at"]) if data.get("started_at") else None,
            completed_at=datetime.fromisoformat(data["completed_at"]) if data.get("completed_at") else None,
            reverted_at=datetime.fromisoformat(data["reverted_at"]) if data.get("reverted_at") else None,
        )


class QualityGate:
    """质量门控记录（synth-loop 自定）"""
    def __init__(self, phase_index: int, gate_type: str, result: str,
                 detail: Optional[str] = None, evaluated_at: Optional[datetime] = None):
        self.phase_index = phase_index
        self.gate_type = gate_type
        self.result = result
        self.detail = detail
        self.evaluated_at = evaluated_at or datetime.now()

    def to_dict(self) -> dict:
        return {
            "phase_index": self.phase_index, "gate_type": self.gate_type,
            "result": self.result, "detail": self.detail,
            "evaluated_at": self.evaluated_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "QualityGate":
        return cls(
            phase_index=data["phase_index"], gate_type=data["gate_type"],
            result=data["result"], detail=data.get("detail"),
            evaluated_at=datetime.fromisoformat(data["evaluated_at"]) if data.get("evaluated_at") else None,
        )


class Artifact:
    """制品记录（T10 桩）"""
    def __init__(self, phase_index: int, name: str, artifact_type: str,
                 local_path: str, cdn_url: Optional[str] = None,
                 size_bytes: Optional[int] = None, created_at: Optional[datetime] = None):
        self.phase_index = phase_index
        self.name = name
        self.type = artifact_type
        self.local_path = local_path
        self.cdn_url = cdn_url
        self.size_bytes = size_bytes
        self.created_at = created_at or datetime.now()

    def to_dict(self) -> dict:
        return {
            "phase_index": self.phase_index, "name": self.name,
            "type": self.type, "local_path": self.local_path,
            "cdn_url": self.cdn_url, "size_bytes": self.size_bytes,
            "created_at": self.created_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Artifact":
        return cls(
            phase_index=data["phase_index"], name=data["name"],
            artifact_type=data["type"], local_path=data["local_path"],
            cdn_url=data.get("cdn_url"), size_bytes=data.get("size_bytes"),
            created_at=datetime.fromisoformat(data["created_at"]) if data.get("created_at") else None,
        )


class AsyncTask:
    """异步任务记录（T8）"""
    def __init__(self, task_id: str, phase_index: int, status: str = "pending",
                 text_cli_task_id: Optional[str] = None, created_at: Optional[datetime] = None):
        self.task_id = task_id
        self.phase_index = phase_index
        self.status = status
        self.text_cli_task_id = text_cli_task_id
        self.created_at = created_at or datetime.now()

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id, "phase_index": self.phase_index,
            "status": self.status, "text_cli_task_id": self.text_cli_task_id,
            "created_at": self.created_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "AsyncTask":
        return cls(
            task_id=data["task_id"], phase_index=data["phase_index"],
            status=data.get("status", "pending"),
            text_cli_task_id=data.get("text_cli_task_id"),
            created_at=datetime.fromisoformat(data["created_at"]) if data.get("created_at") else None,
        )


class PipelineGates:
    """管道级双门控制"""
    def __init__(self, confirm_plan: bool = False, confirm_start: bool = False):
        self.confirm_plan = confirm_plan
        self.confirm_start = confirm_start

    def to_dict(self) -> dict:
        return {"confirm_plan": self.confirm_plan, "confirm_start": self.confirm_start}

    @classmethod
    def from_dict(cls, data: dict) -> "PipelineGates":
        return cls(
            confirm_plan=data.get("confirm_plan", False),
            confirm_start=data.get("confirm_start", False),
        )


# ═══════════════════════════════════════════════════════════
# PipelineSession 主模型
# ═══════════════════════════════════════════════════════════

class PipelineSession:
    """管道会话——跨项目单一真相来源"""

    def __init__(self, intent: str, plan_config: PlanConfig,
                 user_id: Optional[str] = None, pipeline_id: Optional[str] = None,
                 pipeline_gates: Optional[PipelineGates] = None):
        self.pipeline_id = pipeline_id or str(uuid4())
        self.user_id = user_id
        self.intent = intent
        self.status = PipelineStatus.DRAFT
        self.pipeline_gates = pipeline_gates or PipelineGates()
        self.plan_config = plan_config
        self.phases: list[PhaseDefinition] = []
        self.phase_history: list[PhaseHistory] = []
        self.accumulated_context: str = ""
        self.quality_gates: list[QualityGate] = []
        self.artifacts: list[Artifact] = []
        self.async_tasks: list[AsyncTask] = []
        self.created_at = datetime.now()
        self.updated_at = datetime.now()

        # == T11 V0.1.3 预埋（注册不激活） ==
        self.waiting_human_authorization: Optional[bool] = None
        self.physical_safety_check: Optional[dict] = None
        self.cost_tracking: Optional[dict] = None

    def to_dict(self) -> dict:
        return {
            "pipeline_id": self.pipeline_id,
            "user_id": self.user_id,
            "intent": self.intent,
            "status": self.status.value,
            "pipeline_gates": self.pipeline_gates.to_dict(),
            "plan_config": self.plan_config.to_dict(),
            "phases": [p.to_dict() for p in self.phases],
            "phase_history": [h.to_dict() for h in self.phase_history],
            "accumulated_context": self.accumulated_context,
            "quality_gates": [g.to_dict() for g in self.quality_gates],
            "artifacts": [a.to_dict() for a in self.artifacts],
            "async_tasks": [t.to_dict() for t in self.async_tasks],
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            # T11 预埋
            "waiting_human_authorization": self.waiting_human_authorization,
            "physical_safety_check": self.physical_safety_check,
            "cost_tracking": self.cost_tracking,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "PipelineSession":
        session = cls(
            intent=data["intent"],
            plan_config=PlanConfig.from_dict(data["plan_config"]),
            user_id=data.get("user_id"),
            pipeline_id=data.get("pipeline_id"),
            pipeline_gates=PipelineGates.from_dict(data.get("pipeline_gates", {})),
        )
        session.status = PipelineStatus(data.get("status", "draft"))
        session.phases = [PhaseDefinition.from_dict(p) for p in data.get("phases", [])]
        session.phase_history = [PhaseHistory.from_dict(h) for h in data.get("phase_history", [])]
        session.accumulated_context = data.get("accumulated_context", "")
        session.quality_gates = [QualityGate.from_dict(g) for g in data.get("quality_gates", [])]
        session.artifacts = [Artifact.from_dict(a) for a in data.get("artifacts", [])]
        session.async_tasks = [AsyncTask.from_dict(t) for t in data.get("async_tasks", [])]
        session.created_at = datetime.fromisoformat(data["created_at"]) if data.get("created_at") else datetime.now()
        session.updated_at = datetime.fromisoformat(data["updated_at"]) if data.get("updated_at") else datetime.now()
        # T11 预埋
        session.waiting_human_authorization = data.get("waiting_human_authorization")
        session.physical_safety_check = data.get("physical_safety_check")
        session.cost_tracking = data.get("cost_tracking")
        return session

    # == Pipeline 状态转换 ==

    def confirm_plan(self) -> None:
        """确认计划（管道级闸1）"""
        if self.status != PipelineStatus.DRAFT:
            raise ValueError(f"Cannot confirm_plan in status: {self.status}")
        # 门控逻辑由调用方检查 pipeline_gates.confirm_plan

    def start(self) -> None:
        """启动管道（管道级闸2）"""
        allowed = {PipelineStatus.DRAFT}
        if self.status not in allowed:
            raise ValueError(f"Cannot start from status: {self.status}")
        self.status = PipelineStatus.ACTIVE
        self.updated_at = datetime.now()
        # 初始化相位列表
        self.phases = [
            PhaseDefinition(
                index=pc.index, name=pc.name, description=pc.description,
                mode=pc.mode, mode_params=pc.mode_params, gates=pc.gates,
            )
            for pc in self.plan_config.phases
        ]

    def pause(self, reason: str = "") -> None:
        """暂停管道"""
        if self.status != PipelineStatus.ACTIVE:
            raise ValueError(f"Cannot pause from status: {self.status}")
        self.status = PipelineStatus.PAUSED
        self.updated_at = datetime.now()
        # 暂停当前相位
        for p in self.phases:
            if p.status == PhaseStatus.RUNNING:
                p.status = PhaseStatus.PENDING  # 恢复时重试

    def resume(self) -> None:
        """恢复管道"""
        if self.status != PipelineStatus.PAUSED:
            raise ValueError(f"Cannot resume from status: {self.status}")
        self.status = PipelineStatus.ACTIVE
        self.updated_at = datetime.now()

    def complete(self) -> None:
        """完成管道"""
        if self.status != PipelineStatus.ACTIVE:
            raise ValueError(f"Cannot complete from status: {self.status}")
        self.status = PipelineStatus.COMPLETED
        self.updated_at = datetime.now()

    def abort(self, reason: str = "") -> None:
        """中止管道"""
        if self.status in {PipelineStatus.COMPLETED, PipelineStatus.ABORTED}:
            raise ValueError(f"Cannot abort from terminal status: {self.status}")
        self.status = PipelineStatus.ABORTED
        self.updated_at = datetime.now()
        # 中止所有非终态相位
        for p in self.phases:
            if p.status not in {PhaseStatus.COMPLETED, PhaseStatus.FAILED}:
                p.status = PhaseStatus.FAILED

    # == 相位操作 ==

    def get_current_phase(self) -> Optional[PhaseDefinition]:
        """获取当前活跃相位"""
        for p in self.phases:
            if p.status in {PhaseStatus.PENDING, PhaseStatus.RUNNING,
                            PhaseStatus.AWAITING_PATH_CONFIRM, PhaseStatus.AWAITING_APPROVAL}:
                return p
        return None

    def advance_phase(self, phase_index: int, new_status: PhaseStatus, output: str = "") -> None:
        """推进相位状态并记录历史"""
        if phase_index < 0 or phase_index >= len(self.phases):
            raise IndexError(f"Phase {phase_index} out of range")
        phase = self.phases[phase_index]
        old_status = phase.status
        phase.status = new_status

        # 记录历史
        history = PhaseHistory(
            index=phase_index, status=new_status, output=output or None,
            gates=phase.gates, started_at=datetime.now() if new_status == PhaseStatus.RUNNING else None,
            completed_at=datetime.now() if new_status == PhaseStatus.COMPLETED else None,
        )
        self.phase_history.append(history)
        self.updated_at = datetime.now()
        return history

    def add_quality_gate(self, phase_index: int, gate_type: str, result: str, detail: str = "") -> QualityGate:
        """记录质量门控结果"""
        gate = QualityGate(
            phase_index=phase_index, gate_type=gate_type, result=result, detail=detail,
        )
        self.quality_gates.append(gate)
        self.updated_at = datetime.now()
        return gate

    def add_artifact(self, phase_index: int, name: str, artifact_type: str, local_path: str,
                     cdn_url: Optional[str] = None) -> Artifact:
        """记录制品"""
        artifact = Artifact(
            phase_index=phase_index, name=name, artifact_type=artifact_type,
            local_path=local_path, cdn_url=cdn_url,
        )
        self.artifacts.append(artifact)
        self.updated_at = datetime.now()
        return artifact
