"""
JobStore - 监听 Job + 分析 Job 管理
SQLite 持久化的 Job 存储，参考 chat-agent-by-Browser 设计。
"""

import json
import logging
from datetime import datetime
from typing import Any, Optional

import aiosqlite

from ..database import get_db_path

logger = logging.getLogger(__name__)


class JobRecord:
    """Job 记录"""

    def __init__(self, data: dict[str, Any]):
        self.id: str = data["id"]
        self.job_type: str = data.get("job_type", "listener")
        self.status: str = data.get("status", "pending")
        self.session_id: Optional[str] = data.get("session_id")
        self.config: dict = json.loads(data.get("config_json", "{}"))
        self.result: dict = json.loads(data.get("result_json", "{}"))
        self.created_at: str = data.get("created_at", "")
        self.updated_at: str = data.get("updated_at", "")


class JobStore:
    """Job 持久化存储"""

    async def create(
        self,
        job_id: str,
        job_type: str = "listener",
        session_id: Optional[str] = None,
        config: Optional[dict] = None,
    ) -> JobRecord:
        """创建 Job"""
        db_path = get_db_path()
        async with aiosqlite.connect(db_path) as db:
            now = datetime.utcnow().isoformat()
            await db.execute(
                """
                INSERT INTO job_store (id, job_type, status, session_id, config_json, created_at, updated_at)
                VALUES (?, ?, 'pending', ?, ?, ?, ?)
            """,
                (job_id, job_type, session_id, json.dumps(config or {}), now, now),
            )
            await db.commit()

        record = await self.get(job_id)
        if record is None:
            raise RuntimeError(f"Failed to create job: {job_id}")
        logger.info(f"Job created: {job_id} (type={job_type})")
        return record

    async def get(self, job_id: str) -> Optional[JobRecord]:
        """获取 Job"""
        db_path = get_db_path()
        async with aiosqlite.connect(db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM job_store WHERE id = ?", (job_id,)
            )
            row = await cursor.fetchone()
            if row is None:
                return None
            return JobRecord(dict(row))

    async def update_status(self, job_id: str, status: str, result: Optional[dict] = None) -> bool:
        """更新 Job 状态"""
        db_path = get_db_path()
        async with aiosqlite.connect(db_path) as db:
            now = datetime.utcnow().isoformat()
            result_json = json.dumps(result) if result else None
            if result_json is not None:
                await db.execute(
                    "UPDATE job_store SET status = ?, result_json = ?, updated_at = ? WHERE id = ?",
                    (status, result_json, now, job_id),
                )
            else:
                await db.execute(
                    "UPDATE job_store SET status = ?, updated_at = ? WHERE id = ?",
                    (status, now, job_id),
                )
            await db.commit()
            cursor = await db.execute("SELECT changes()")
            row = await cursor.fetchone()
            updated = row[0] > 0 if row else False
            if updated:
                logger.info(f"Job status updated: {job_id} -> {status}")
            return updated

    async def list_by_type(self, job_type: str, status: Optional[str] = None) -> list[JobRecord]:
        """按类型和状态查询 Job"""
        db_path = get_db_path()
        async with aiosqlite.connect(db_path) as db:
            db.row_factory = aiosqlite.Row
            if status:
                cursor = await db.execute(
                    "SELECT * FROM job_store WHERE job_type = ? AND status = ? ORDER BY created_at DESC",
                    (job_type, status),
                )
            else:
                cursor = await db.execute(
                    "SELECT * FROM job_store WHERE job_type = ? ORDER BY created_at DESC",
                    (job_type,),
                )
            rows = await cursor.fetchall()
            return [JobRecord(dict(row)) for row in rows]

    async def list_by_session(self, session_id: str) -> list[JobRecord]:
        """按 session_id 查询 Job"""
        db_path = get_db_path()
        async with aiosqlite.connect(db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM job_store WHERE session_id = ? ORDER BY created_at DESC",
                (session_id,),
            )
            rows = await cursor.fetchall()
            return [JobRecord(dict(row)) for row in rows]

    async def delete(self, job_id: str) -> bool:
        """删除 Job"""
        db_path = get_db_path()
        async with aiosqlite.connect(db_path) as db:
            cursor = await db.execute("DELETE FROM job_store WHERE id = ?", (job_id,))
            await db.commit()
            return cursor.rowcount > 0


# 全局实例
_job_store: Optional[JobStore] = None


def get_job_store() -> JobStore:
    """获取 JobStore 实例"""
    global _job_store
    if _job_store is None:
        _job_store = JobStore()
    return _job_store
