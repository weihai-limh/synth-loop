"""Session 数据结构定义 - v0.5 新增字段"""

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional


@dataclass
class Session:
    """会话数据结构"""

    session_id: str
    permanent_system_prompt: str = ""
    loaded_docs: list[dict[str, str]] = field(default_factory=list)
    temp_history: deque[dict[str, Any]] = field(default_factory=lambda: deque(maxlen=20))
    created_at: datetime = field(default_factory=datetime.now)
    last_active: datetime = field(default_factory=datetime.now)
    round_counter: int = 0
    snapshot_dirty: bool = False

    # v0.5 新增字段
    downstream_session_id: Optional[str] = None
    active_job_id: Optional[str] = None
    active_chain_id: Optional[str] = None
    last_complexity: Optional[str] = None     # chat / prompt_chat / task_chain
    last_logic_category: Optional[str] = None  # document_writing / code_generation / ...

    def update_active(self) -> None:
        """更新最后活动时间"""
        self.last_active = datetime.now()

    def increment_round(self) -> None:
        """增加轮次计数器"""
        self.round_counter += 1
        self.snapshot_dirty = True
        self.update_active()

    def set_complexity(self, complexity: str, logic_category: Optional[str] = None):
        """记录最近一次 Dispatch 决策"""
        self.last_complexity = complexity
        if logic_category:
            self.last_logic_category = logic_category
        self.snapshot_dirty = True

    def set_active_job(self, job_id: Optional[str]):
        """设置当前活跃 Job"""
        self.active_job_id = job_id
        self.snapshot_dirty = True

    def set_active_chain(self, chain_id: Optional[str]):
        """设置当前活跃任务链"""
        self.active_chain_id = chain_id
        self.snapshot_dirty = True

    def to_snapshot_dict(self) -> dict[str, Any]:
        """转换为快照字典（用于持久化，包含 v0.5 新增字段）"""
        return {
            "session_id": self.session_id,
            "permanent_system_prompt": self.permanent_system_prompt,
            "loaded_docs_json": self.loaded_docs,
            "last_interaction_json": list(self.temp_history)[-2:] if self.temp_history else [],
            "last_active_time": self.last_active.isoformat(),
            # v0.5 新增字段持久化
            "downstream_session_id": self.downstream_session_id,
            "active_job_id": self.active_job_id,
            "active_chain_id": self.active_chain_id,
            "last_complexity": self.last_complexity,
            "last_logic_category": self.last_logic_category,
        }

    @classmethod
    def from_snapshot_dict(cls, data: dict[str, Any], max_temp_messages: int = 20) -> "Session":
        """从快照字典恢复 Session（兼容 v0.5 新增字段）"""
        session = cls(
            session_id=data["session_id"],
            permanent_system_prompt=data.get("permanent_system_prompt", ""),
            loaded_docs=data.get("loaded_docs_json", []),
            # v0.5 新增字段恢复
            downstream_session_id=data.get("downstream_session_id"),
            active_job_id=data.get("active_job_id"),
            active_chain_id=data.get("active_chain_id"),
            last_complexity=data.get("last_complexity"),
            last_logic_category=data.get("last_logic_category"),
        )
        session.temp_history = deque(data.get("last_interaction_json", []), maxlen=max_temp_messages)
        if data.get("last_active_time"):
            session.last_active = datetime.fromisoformat(data["last_active_time"])
        return session
