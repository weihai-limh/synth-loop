"""运行时表服务（_a P2.1）——tc 消费链路配置面

- runtime_endpoints 表 CRUD（token 脱敏返回）
- 配置种子灌入（幂等）
- token 加密存储（SELF_TOKEN_ENC_KEY，缺失 WARNING + 明文内网降级）
- alias 解析：alias → (url, auth, token)；default_alias 兜底；同 alias rank 降级

对齐：tc 消费侧 agent-endpoints.json + sm tc_endpoints——项目族"接入注册表模式"。
"""

import logging
import os
import uuid
from typing import Optional

from app.database import get_shared_db

logger = logging.getLogger(__name__)

_ENC_KEY_ENV = "SELF_TOKEN_ENC_KEY"


# ═══════════════════════════════════════════════════════════
# token 加密（轻量 XOR + key；生产应换 AES，契约不变）
# ═══════════════════════════════════════════════════════════

def _enc_key() -> Optional[str]:
    key = os.environ.get(_ENC_KEY_ENV, "")
    if not key:
        logger.warning(f"{_ENC_KEY_ENV} not set; tokens stored in plaintext (LAN degraded mode). MUST be configured in production")
        return None
    return key


def _encrypt_token(token: str) -> str:
    key = _enc_key()
    if not key or not token:
        return token
    # XOR 加密（轻量；密钥缺失时明文降级）
    return "".join(chr(ord(c) ^ ord(key[i % len(key)])) for i, c in enumerate(token))


def _decrypt_token(token: str) -> str:
    key = _enc_key()
    if not key or not token:
        return token
    return "".join(chr(ord(c) ^ ord(key[i % len(key)])) for i, c in enumerate(token))


def _mask_token(token: str) -> str:
    """脱敏：sk-***（仅展示前缀）"""
    if not token:
        return ""
    if len(token) <= 4:
        return "***"
    return token[:4] + "***"


# ═══════════════════════════════════════════════════════════
# 种子灌入
# ═══════════════════════════════════════════════════════════

async def seed_runtime_endpoints(config: dict) -> None:
    """启动时从 config.yaml runtime_endpoints.seeds 灌入（幂等，已存在跳过）"""
    section = config.get("runtime_endpoints") or {}
    if not section.get("enabled", False):
        return
    seeds = section.get("seeds", [])
    db = await get_shared_db()
    for seed in seeds:
        alias = seed.get("alias")
        if not alias:
            continue
        # 幂等：同 alias + 同 url 视为已存在
        cursor = await db.execute(
            "SELECT id FROM runtime_endpoints WHERE alias = ? AND url = ?",
            (alias, seed.get("url", "")),
        )
        row = await cursor.fetchone()
        if row:
            continue
        await db.execute(
            """INSERT INTO runtime_endpoints
               (id, alias, kind, url, auth, service_token, access_token, rank, trust, is_active)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                str(uuid.uuid4()),
                alias,
                seed.get("kind", "runtime"),
                seed["url"],
                seed.get("auth", "none"),
                _encrypt_token(seed.get("service_token", "")),
                _encrypt_token(seed.get("access_token", "")),
                seed.get("rank", 100),
                seed.get("trust", "internal"),
                1,
            ),
        )
        logger.info(f"Runtime table seed: {alias}")
    await db.commit()


# ═══════════════════════════════════════════════════════════
# CRUD（管理 API 用；token 脱敏返回）
# ═══════════════════════════════════════════════════════════

def _mask_row(row: dict) -> dict:
    """脱敏行：token 字段只留前缀"""
    masked = dict(row)
    if masked.get("service_token"):
        masked["service_token"] = _mask_token(masked["service_token"])
    if masked.get("access_token"):
        masked["access_token"] = _mask_token(masked["access_token"])
    return masked


async def list_endpoints() -> list[dict]:
    db = await get_shared_db()
    cursor = await db.execute(
        "SELECT * FROM runtime_endpoints ORDER BY rank, alias"
    )
    rows = await cursor.fetchall()
    return [_mask_row(dict(r)) for r in rows]


async def create_endpoint(data: dict) -> dict:
    db = await get_shared_db()
    import uuid
    endpoint_id = str(uuid.uuid4())
    await db.execute(
        """INSERT INTO runtime_endpoints
           (id, alias, kind, url, auth, service_token, access_token, rank, trust, is_active)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            endpoint_id,
            data["alias"],
            data.get("kind", "runtime"),
            data["url"],
            data.get("auth", "none"),
            _encrypt_token(data.get("service_token", "")),
            _encrypt_token(data.get("access_token", "")),
            data.get("rank", 100),
            data.get("trust", "internal"),
            data.get("is_active", 1),
        ),
    )
    await db.commit()
    cursor = await db.execute("SELECT * FROM runtime_endpoints WHERE id = ?", (endpoint_id,))
    row = await cursor.fetchone()
    return _mask_row(dict(row))


async def update_endpoint(alias: str, data: dict) -> Optional[dict]:
    """按 alias 更新（同 alias 多行全部更新——换 url/rank 属配置变更）"""
    db = await get_shared_db()
    cursor = await db.execute("SELECT id FROM runtime_endpoints WHERE alias = ?", (alias,))
    if not await cursor.fetchone():
        return None
    # 只更新提供的字段
    fields = []
    params = []
    for key in ("url", "auth", "rank", "trust", "is_active", "kind"):
        if key in data:
            fields.append(f"{key} = ?")
            params.append(data[key])
    for key in ("service_token", "access_token"):
        if key in data:
            fields.append(f"{key} = ?")
            params.append(_encrypt_token(data[key]))
    if fields:
        fields.append("updated_at = CURRENT_TIMESTAMP")
        params.append(alias)
        await db.execute(
            f"UPDATE runtime_endpoints SET {', '.join(fields)} WHERE alias = ?",
            params,
        )
        await db.commit()
    cursor = await db.execute("SELECT * FROM runtime_endpoints WHERE alias = ?", (alias,))
    rows = await cursor.fetchall()
    return [_mask_row(dict(r)) for r in rows] if rows else None


async def delete_endpoint(alias: str) -> bool:
    db = await get_shared_db()
    cursor = await db.execute("DELETE FROM runtime_endpoints WHERE alias = ?", (alias,))
    await db.commit()
    return cursor.rowcount > 0


# ═══════════════════════════════════════════════════════════
# 解析（强化客户端消费）
# ═══════════════════════════════════════════════════════════

async def resolve_alias(alias: Optional[str], default_alias: Optional[str] = None) -> list[dict]:
    """解析 alias → 按 rank 递增的物理行列表。

    - alias 提供且注册 → 精确路由（同 alias 多行按 rank 排序）
    - alias None/未知 → default_alias；未配置 default_alias → rank 最小者兜底
    - 全部 active 行（is_active=1）
    """
    db = await get_shared_db()

    # 路由层：选 alias
    target = alias
    if target:
        cursor = await db.execute(
            "SELECT id FROM runtime_endpoints WHERE alias = ? AND is_active = 1 LIMIT 1",
            (target,),
        )
        if not await cursor.fetchone():
            target = default_alias  # 未知 alias → 回落默认
    if not target:
        target = default_alias
    if not target:
        # 未配置 default_alias → rank 最小者
        cursor = await db.execute(
            "SELECT alias FROM runtime_endpoints WHERE is_active = 1 ORDER BY rank, alias LIMIT 1"
        )
        row = await cursor.fetchone()
        if not row:
            return []
        target = row["alias"]

    # 容错层：同 alias 多物理行按 rank 递增
    cursor = await db.execute(
        """SELECT alias, kind, url, auth, service_token, access_token, rank
           FROM runtime_endpoints WHERE alias = ? AND is_active = 1
           ORDER BY rank, updated_at""",
        (target,),
    )
    rows = await cursor.fetchall()
    result = []
    for r in rows:
        d = dict(r)
        d["service_token"] = _decrypt_token(d.get("service_token") or "")
        d["access_token"] = _decrypt_token(d.get("access_token") or "")
        result.append(d)
    return result
