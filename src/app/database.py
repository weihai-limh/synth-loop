"""数据库连接与初始化模块"""

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import aiosqlite

from .config import get_section, SRC_DIR

# 全局数据库连接
_db_path: str | None = None


def get_db_path() -> str:
    """获取数据库路径（相对于 SRC_DIR 解析）"""
    global _db_path
    if _db_path is None:
        db_config = get_section("database")
        _db_path = str(SRC_DIR / db_config["path"])
    return _db_path


async def init_database() -> None:
    """初始化数据库表结构"""
    db_path = get_db_path()
    # 确保目录存在
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    async with aiosqlite.connect(db_path) as db:
        # 创建会话快照表（v0.5 新增字段）
        await db.execute("""
            CREATE TABLE IF NOT EXISTS session_snapshots (
                session_id TEXT PRIMARY KEY,
                permanent_system_prompt TEXT DEFAULT '',
                loaded_docs_json TEXT DEFAULT '[]',
                last_interaction_json TEXT DEFAULT '[]',
                last_active_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                downstream_session_id TEXT,
                active_job_id TEXT,
                active_chain_id TEXT,
                last_complexity TEXT,
                last_logic_category TEXT
            )
        """)
        # 向前兼容：为现有表添加新列
        await _add_column_if_not_exists(db, "session_snapshots", "downstream_session_id", "TEXT")
        await _add_column_if_not_exists(db, "session_snapshots", "active_job_id", "TEXT")
        await _add_column_if_not_exists(db, "session_snapshots", "active_chain_id", "TEXT")
        await _add_column_if_not_exists(db, "session_snapshots", "last_complexity", "TEXT")
        await _add_column_if_not_exists(db, "session_snapshots", "last_logic_category", "TEXT")
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_snapshot_active 
            ON session_snapshots(last_active_time)
        """)

        # 创建消息记录表（二期可选）
        await db.execute("""
            CREATE TABLE IF NOT EXISTS message_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                round_number INTEGER NOT NULL,
                direction TEXT NOT NULL CHECK(direction IN ('request','response')),
                payload TEXT NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_logs_session_round 
            ON message_logs(session_id, round_number)
        """)

        # 创建 Job Store 表
        await db.execute("""
            CREATE TABLE IF NOT EXISTS job_store (
                id TEXT PRIMARY KEY,
                job_type TEXT NOT NULL DEFAULT 'listener',
                status TEXT NOT NULL DEFAULT 'pending',
                session_id TEXT,
                config_json TEXT DEFAULT '{}',
                result_json TEXT DEFAULT '{}',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_job_store_status 
            ON job_store(status)
        """)
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_job_store_type 
            ON job_store(job_type)
        """)

        # v0_1_1 新增: 用户表
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                enabled BOOLEAN DEFAULT true,
                display_name TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # v0_1_1 新增: 异步任务表
        await db.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                id TEXT PRIMARY KEY,
                session_id TEXT,
                user_id TEXT,
                input TEXT,
                status TEXT NOT NULL DEFAULT 'queued',
                result TEXT,
                error TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_tasks_status 
            ON tasks(status)
        """)
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_tasks_user_id 
            ON tasks(user_id)
        """)

        await db.commit()


async def _add_column_if_not_exists(db: aiosqlite.Connection, table: str, column: str, col_type: str):
    """安全添加列（如果不存在）"""
    try:
        cursor = await db.execute(f"SELECT {column} FROM {table} LIMIT 1")
        await cursor.fetchone()
    except Exception:
        await db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")


async def save_session_snapshot(
    session_id: str,
    permanent_system_prompt: str,
    loaded_docs: list[dict[str, str]],
    last_interaction: list[dict[str, Any]],
    last_active_time: datetime,
    downstream_session_id: str | None = None,
    active_job_id: str | None = None,
    active_chain_id: str | None = None,
    last_complexity: str | None = None,
    last_logic_category: str | None = None,
) -> None:
    """保存或更新会话快照（v0.5 新增字段）"""
    db_path = get_db_path()
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            """
            INSERT OR REPLACE INTO session_snapshots 
            (session_id, permanent_system_prompt, loaded_docs_json, last_interaction_json, last_active_time,
             downstream_session_id, active_job_id, active_chain_id, last_complexity, last_logic_category)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                session_id,
                permanent_system_prompt,
                json.dumps(loaded_docs, ensure_ascii=False),
                json.dumps(last_interaction, ensure_ascii=False),
                last_active_time.isoformat(),
                downstream_session_id,
                active_job_id,
                active_chain_id,
                last_complexity,
                last_logic_category,
            ),
        )
        await db.commit()


async def load_session_snapshot(session_id: str) -> dict[str, Any] | None:
    """加载会话快照"""
    db_path = get_db_path()
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM session_snapshots WHERE session_id = ?", (session_id,)
        )
        row = await cursor.fetchone()
        if row is None:
            return None

        return {
            "session_id": row["session_id"],
            "permanent_system_prompt": row["permanent_system_prompt"],
            "loaded_docs_json": json.loads(row["loaded_docs_json"]),
            "last_interaction_json": json.loads(row["last_interaction_json"]),
            "last_active_time": row["last_active_time"],
            # v0.5 新增字段（可空）
            "downstream_session_id": row["downstream_session_id"] if "downstream_session_id" in row.keys() else None,
            "active_job_id": row["active_job_id"] if "active_job_id" in row.keys() else None,
            "active_chain_id": row["active_chain_id"] if "active_chain_id" in row.keys() else None,
            "last_complexity": row["last_complexity"] if "last_complexity" in row.keys() else None,
            "last_logic_category": row["last_logic_category"] if "last_logic_category" in row.keys() else None,
        }


async def delete_session_snapshot(session_id: str) -> bool:
    """删除会话快照"""
    db_path = get_db_path()
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute(
            "DELETE FROM session_snapshots WHERE session_id = ?", (session_id,)
        )
        await db.commit()
        return cursor.rowcount > 0


async def cleanup_expired_sessions(expire_days: int) -> int:
    """清理过期会话"""
    db_path = get_db_path()
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute(
            """
            DELETE FROM session_snapshots 
            WHERE last_active_time < datetime('now', ? || ' days')
        """,
            (f"-{expire_days}",),
        )
        await db.commit()
        return cursor.rowcount


async def get_active_session_count() -> int:
    """获取活跃会话数量"""
    db_path = get_db_path()
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute("SELECT COUNT(*) FROM session_snapshots")
        row = await cursor.fetchone()
        return row[0] if row else 0


# ═══════════════════════════════════════════════════════════
# v0_1_1 新增: tasks 表查询
# ═══════════════════════════════════════════════════════════

async def get_task(task_id: str) -> dict[str, Any] | None:
    """查询单个任务"""
    db_path = get_db_path()
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
        row = await cursor.fetchone()
        if row is None:
            return None
        return dict(row)


# ═══════════════════════════════════════════════════════════
# v0_1_1 Phase 3: users 表 CRUD
# ═══════════════════════════════════════════════════════════

async def create_user(user_id: str, display_name: str = "", enabled: bool = True) -> dict[str, Any]:
    """创建用户"""
    db_path = get_db_path()
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            """INSERT OR IGNORE INTO users (id, enabled, display_name, created_at, updated_at)
               VALUES (?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)""",
            (user_id, int(enabled), display_name),
        )
        await db.commit()

        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM users WHERE id = ?", (user_id,))
        row = await cursor.fetchone()
        if row is None:
            raise RuntimeError(f"Failed to create user: {user_id}")
        return dict(row)


async def get_user(user_id: str) -> dict[str, Any] | None:
    """查询单个用户"""
    db_path = get_db_path()
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM users WHERE id = ?", (user_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None


async def list_users() -> list[dict[str, Any]]:
    """列出所有用户"""
    db_path = get_db_path()
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM users ORDER BY created_at DESC")
        return [dict(row) for row in await cursor.fetchall()]


async def update_user(user_id: str, enabled: bool | None = None, display_name: str | None = None) -> bool:
    """更新用户（启用/禁用 或 改名）"""
    db_path = get_db_path()
    async with aiosqlite.connect(db_path) as db:
        if enabled is not None:
            cursor = await db.execute(
                "UPDATE users SET enabled = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (int(enabled), user_id),
            )
            if cursor.rowcount == 0:
                return False
        if display_name is not None:
            cursor = await db.execute(
                "UPDATE users SET display_name = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (display_name, user_id),
            )
            if cursor.rowcount == 0:
                return False
        await db.commit()
        return True


async def delete_user(user_id: str) -> bool:
    """删除用户"""
    db_path = get_db_path()
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute("DELETE FROM users WHERE id = ?", (user_id,))
        await db.commit()
        return cursor.rowcount > 0
