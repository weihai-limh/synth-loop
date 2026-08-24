"""数据库连接与初始化模块"""

import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Awaitable, Callable

import aiosqlite

from .config import get_section, SRC_DIR

# 全局数据库连接
_db_path: str | None = None
# v0_1_2: 全局共享连接（lifespan 初始化，避免每次建连）
_db_connection: aiosqlite.Connection | None = None


async def get_shared_db() -> aiosqlite.Connection:
    """v0_1_2: 获取全局共享数据库连接"""
    global _db_connection
    if _db_connection is None:
        db_path = get_db_path()
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        _db_connection = await aiosqlite.connect(db_path)
        _db_connection.row_factory = aiosqlite.Row
        logger = logging.getLogger(__name__)
        logger.info(f"Shared DB connection opened: {db_path}")
    return _db_connection


# ═══════════════════════════════════════════════════════════
# v0_1_2_d (B0): 写入串行化封装
# 单共享连接下，多个并发写必须串行提交，避免 SQLite 锁冲突 /
# 跨 await 复用错误。模块级锁保证「一个写事务完整提交前，另一个不开始」。
# ⚠ 注意：本 Phase 仅引入封装，运行期调用点收敛在 Phase 2 (B1)。
# ═══════════════════════════════════════════════════════════
_write_lock = asyncio.Lock()


async def execute_write(db: aiosqlite.Connection, sql: str, params: tuple = ()) -> aiosqlite.Cursor:
    """写操作统一入口：持 _write_lock，保证一个写事务完整提交前另一个不开始。"""
    async with _write_lock:
        cur = await db.execute(sql, params)
        await db.commit()
        return cur


async def execute_read(db: aiosqlite.Connection, sql: str, params: tuple = ()) -> aiosqlite.Cursor:
    """读操作：不持写锁（SQLite 多读单写，读间可并发）。"""
    return await db.execute(sql, params)


async def write_transaction(
    db: aiosqlite.Connection, coro: Callable[[], Awaitable[Any]]
) -> Any:
    """复合写包裹器：在持锁范围内跑「读-改-写」协程并统一 commit。
    用于含中间 await 的复合操作（如 update_user / cleanup_expired_sessions /
    create_user），避免锁外交错导致跨 await 复用错误。
    Phase 2 (B1) 收敛时这些复合写函数须包进本包裹器。"""
    async with _write_lock:
        result = await coro()
        await db.commit()
        return result


async def close_shared_db() -> None:
    """v0_1_2: 关闭全局共享数据库连接"""
    global _db_connection
    if _db_connection is not None:
        await _db_connection.close()
        _db_connection = None


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

        # _a 新增: 运行时表（tc 消费链路配置面，P7/P8/P10 落点）
        # 注意：alias 非唯一——同 alias 多物理行按 rank 降级（对齐 sm tc_endpoints 结构）
        await db.execute("""
            CREATE TABLE IF NOT EXISTS runtime_endpoints (
                id               TEXT PRIMARY KEY,
                alias            TEXT NOT NULL,   -- 逻辑端点名（对齐 sm tc_endpoints.alias）
                kind             TEXT NOT NULL DEFAULT 'runtime',  -- runtime(直连 Service) | endpoint(集成网关)
                url              TEXT NOT NULL,      -- 完整端点 URL
                auth             TEXT NOT NULL DEFAULT 'none',     -- none | single | dual
                service_token    TEXT DEFAULT '',    -- 加密存储；支持 ${ENV_VAR}
                access_token     TEXT DEFAULT '',    -- 加密存储；kind=endpoint 时使用
                rank             INTEGER DEFAULT 100, -- 降级优先级（数值小者优先）
                trust            TEXT DEFAULT 'internal',
                is_active        INTEGER DEFAULT 1,
                created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("CREATE INDEX IF NOT EXISTS idx_runtime_endpoints_alias ON runtime_endpoints(alias)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_runtime_endpoints_rank ON runtime_endpoints(alias, rank)")

        # _a P4: tokens 表（统一请求 token 层——sha256 hash 过渡态 + scope 分层 + 预留列）
        await db.execute("""
            CREATE TABLE IF NOT EXISTS tokens (
                id            TEXT PRIMARY KEY,
                token_hash    TEXT NOT NULL,
                service       TEXT NOT NULL,         -- sl | sm（结构统一，预留未来统一表/管理服务）
                scope         TEXT NOT NULL,         -- user | service | admin
                user_id       TEXT,
                display_name  TEXT DEFAULT '',
                expires_at    TIMESTAMP,             -- 预留过期（未来启用，NULL=永不过期）
                revoked_at    TIMESTAMP,             -- 预留撤销（未来启用，NULL=有效）
                created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("CREATE INDEX IF NOT EXISTS idx_tokens_hash ON tokens(token_hash)")

        # _a P4.3: artifacts 表（数据面下行——相位产物存储，TTL 24h）
        # _c: phase_index_txt 承载 pk 的 phase_path 树路径（如 "0-1"）；artifact_id 唯一必填，其余可空
        await db.execute("""
            CREATE TABLE IF NOT EXISTS artifacts (
                artifact_id TEXT PRIMARY KEY,
                pipeline_id TEXT,
                kind TEXT,              -- plan | path | result | summary
                phase_index INTEGER,    -- 旧扁平索引（兼容遗留）
                phase_index_txt TEXT,   -- _c 新增：phase_path 树路径（如 "0-1"）
                content TEXT,           -- JSON 序列化（str 或 dict）
                summary TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                expires_at TIMESTAMP
            )
        """)
        await db.execute("CREATE INDEX IF NOT EXISTS idx_artifacts_pipeline ON artifacts(pipeline_id)")
        # _c 迁移：旧库加 phase_index_txt 列（不丢数据）
        await _add_column_if_not_exists(db, "artifacts", "phase_index_txt", "TEXT")
        await db.execute(
            "UPDATE artifacts SET phase_index_txt = CAST(phase_index AS TEXT) "
            "WHERE phase_index_txt IS NULL AND phase_index IS NOT NULL"
        )

        # _c: longdata 表（永久区通道——doc/memory 引入，无 TTL）
        await db.execute("""
            CREATE TABLE IF NOT EXISTS longdata (
                id         TEXT PRIMARY KEY,          -- 内部 id（add 时生成，等价 loaded_docs.doc_id）
                session_id TEXT NOT NULL,
                type       TEXT NOT NULL,             -- "doc" | "memory"
                content    TEXT NOT NULL,
                created_at REAL
            )
        """)
        await db.execute("CREATE INDEX IF NOT EXISTS idx_longdata_session ON longdata(session_id)")

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
    db = await get_shared_db()
    await execute_write(
        db,
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


async def load_session_snapshot(session_id: str) -> dict[str, Any] | None:
    """加载会话快照"""
    db = await get_shared_db()
    cursor = await execute_read(
        db, "SELECT * FROM session_snapshots WHERE session_id = ?", (session_id,)
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
    db = await get_shared_db()
    cursor = await execute_write(
        db, "DELETE FROM session_snapshots WHERE session_id = ?", (session_id,)
    )
    return cursor.rowcount > 0


# v0_1_2_d (B0 标注): 单步 DELETE（行内 datetime 计算，无中间 await）。用 execute_write。
async def cleanup_expired_sessions(expire_days: int) -> int:
    """清理过期会话"""
    db = await get_shared_db()
    cursor = await execute_write(
        db,
        """
        DELETE FROM session_snapshots 
        WHERE last_active_time < datetime('now', ? || ' days')
    """,
        (f"-{expire_days}",),
    )
    return cursor.rowcount


async def get_active_session_count() -> int:
    """获取活跃会话数量"""
    db = await get_shared_db()
    cursor = await execute_read(db, "SELECT COUNT(*) FROM session_snapshots")
    row = await cursor.fetchone()
    return row[0] if row else 0


# ═══════════════════════════════════════════════════════════
# v0_1_1 新增: tasks 表查询
# ═══════════════════════════════════════════════════════════

async def get_task(task_id: str) -> dict[str, Any] | None:
    """查询单个任务"""
    db = await get_shared_db()
    cursor = await execute_read(db, "SELECT * FROM tasks WHERE id = ?", (task_id,))
    row = await cursor.fetchone()
    if row is None:
        return None
    return dict(row)


# ═══════════════════════════════════════════════════════════
# v0_1_1 Phase 3: users 表 CRUD
# ═══════════════════════════════════════════════════════════

# v0_1_2_d (B0 标注): 复合写（先插 → 查回）。Phase 2 (B1) 已包进 write_transaction。
async def create_user(user_id: str, display_name: str = "", enabled: bool = True) -> dict[str, Any]:
    """创建用户"""
    db = await get_shared_db()

    async def _create() -> dict[str, Any]:
        await db.execute(
            """INSERT OR IGNORE INTO users (id, enabled, display_name, created_at, updated_at)
               VALUES (?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)""",
            (user_id, int(enabled), display_name),
        )
        cursor = await db.execute("SELECT * FROM users WHERE id = ?", (user_id,))
        row = await cursor.fetchone()
        if row is None:
            raise RuntimeError(f"Failed to create user: {user_id}")
        return dict(row)

    return await write_transaction(db, _create)


async def get_user(user_id: str) -> dict[str, Any] | None:
    """查询单个用户"""
    db = await get_shared_db()
    cursor = await execute_read(db, "SELECT * FROM users WHERE id = ?", (user_id,))
    row = await cursor.fetchone()
    return dict(row) if row else None


async def list_users() -> list[dict[str, Any]]:
    """列出所有用户"""
    db = await get_shared_db()
    cursor = await execute_read(db, "SELECT * FROM users ORDER BY created_at DESC")
    return [dict(row) for row in await cursor.fetchall()]


# v0_1_2_d (B0 标注): 复合写（多步 UPDATE + 逐行 rowcount 判断）。Phase 2 (B1) 已包进 write_transaction。
async def update_user(user_id: str, enabled: bool | None = None, display_name: str | None = None) -> bool:
    """更新用户（启用/禁用 或 改名）"""
    db = await get_shared_db()

    async def _update() -> bool:
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
        return True

    return await write_transaction(db, _update)


async def delete_user(user_id: str) -> bool:
    """删除用户"""
    db = await get_shared_db()
    cursor = await execute_write(db, "DELETE FROM users WHERE id = ?", (user_id,))
    return cursor.rowcount > 0
