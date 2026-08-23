"""Session 管理器模块"""

from datetime import datetime, timedelta
from typing import Any, Optional
from uuid import uuid4

from ..config import get_section
from ..database import (
    cleanup_expired_sessions,
    delete_session_snapshot,
    load_session_snapshot,
    save_session_snapshot,
)
from ..models.session import Session


class SessionManager:
    """会话管理器"""

    def __init__(self) -> None:
        self.sessions: dict[str, Session] = {}
        self._config = get_section("session")
        self._max_temp_messages = self._config.get("max_temp_messages", 20)
        self._snapshot_interval = self._config.get("snapshot_interval", 5)
        self._expire_days = self._config.get("expire_days", 3)

    async def get_or_create(self, session_id: Optional[str] = None) -> Session:
        """获取或创建 Session"""
        # 如果指定了 session_id，先从内存查找
        if session_id and session_id in self.sessions:
            session = self.sessions[session_id]
            session.update_active()
            return session

        # 如果指定了 session_id，尝试从 SQLite 恢复
        if session_id:
            session = await self._load_from_snapshot(session_id)
            if session:
                self.sessions[session_id] = session
                session.update_active()
                return session

        # 创建新 Session
        new_id = session_id or str(uuid4())
        session = Session(
            session_id=new_id,
            temp_history=[],  # deque 在 __init__ 中默认创建
        )
        session.temp_history = __import__("collections").deque(
            maxlen=self._max_temp_messages
        )
        self.sessions[new_id] = session

        # 写入 SQLite 初始快照
        await self.save_snapshot(session)
        return session

    async def save_snapshot(self, session: Session) -> None:
        """保存快照到 SQLite（v0.5 新增字段）"""
        # 只保存永久区 + 最后1条交互
        last_interaction = list(session.temp_history)[-2:] if session.temp_history else []

        await save_session_snapshot(
            session_id=session.session_id,
            permanent_system_prompt=session.permanent_system_prompt,
            loaded_docs=session.loaded_docs,
            last_interaction=last_interaction,
            last_active_time=session.last_active,
            # v0.5 新增字段
            downstream_session_id=session.downstream_session_id,
            active_job_id=session.active_job_id,
            active_chain_id=session.active_chain_id,
            last_complexity=session.last_complexity,
            last_logic_category=session.last_logic_category,
        )
        session.snapshot_dirty = False

    async def _load_from_snapshot(self, session_id: str) -> Optional[Session]:
        """从快照恢复 Session"""
        snapshot = await load_session_snapshot(session_id)
        if snapshot is None:
            return None

        session = Session.from_snapshot_dict(snapshot, self._max_temp_messages)
        return session

    async def delete(self, session_id: str) -> bool:
        """删除会话"""
        # 从内存删除
        if session_id in self.sessions:
            del self.sessions[session_id]

        # 从 SQLite 删除
        return await delete_session_snapshot(session_id)

    async def cleanup_expired(self) -> int:
        """清理过期会话"""
        # 清理内存中的过期会话
        expired_ids = []
        expire_threshold = datetime.now() - timedelta(days=self._expire_days)

        for session_id, session in self.sessions.items():
            if session.last_active < expire_threshold:
                expired_ids.append(session_id)

        for session_id in expired_ids:
            del self.sessions[session_id]

        # 清理 SQLite 中的过期会话
        count = await cleanup_expired_sessions(self._expire_days)
        return count

    def get_active_count(self) -> int:
        """获取活跃会话数量"""
        return len(self.sessions)

    @property
    def snapshot_interval(self) -> int:
        """快照间隔（轮次）"""
        return self._snapshot_interval
