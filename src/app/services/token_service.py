"""统一请求 token 层（_a P4，与 sm 同构）

- tokens 表：sha256 hash 过渡态存储 + scope 分层（user/service/admin）+ 预留过期/撤销列
- verify_token(service, token, scope) -> user_id：本地查表；单函数抽象（未来管理服务接缝）
- 默认 auth.enabled=false → 不校验（开箱即用，向后兼容）
"""

import hashlib
import logging
import uuid
from typing import Optional

from app.database import get_shared_db

logger = logging.getLogger(__name__)


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


async def issue_token(token: str, service: str, scope: str,
                      user_id: Optional[str] = None,
                      display_name: str = "") -> dict:
    """签发 token 记录（管理面/种子用；_a 为过渡态——未来管理服务替换）"""
    db = await get_shared_db()
    token_id = str(uuid.uuid4())
    await db.execute(
        """INSERT INTO tokens (id, token_hash, service, scope, user_id, display_name)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (token_id, _hash_token(token), service, scope, user_id, display_name),
    )
    await db.commit()
    return {"id": token_id, "service": service, "scope": scope, "user_id": user_id}


async def verify_token(service: str, token: str, scope: str) -> Optional[str]:
    """校验 token → 返回 user_id（校验通过但无 user_id 时返回 ""，None 仅表示校验失败）。

    现在查本地 tokens 表实现；未来统一 token 管理服务部署时只换此函数实现（远程校验），
    调用方零感知——单函数抽象接缝。
    """
    if not token:
        return None
    db = await get_shared_db()
    cursor = await db.execute(
        """SELECT user_id, revoked_at FROM tokens
           WHERE token_hash = ? AND service = ? AND scope = ?
           AND revoked_at IS NULL""",
        (_hash_token(token), service, scope),
    )
    row = await cursor.fetchone()
    if not row:
        return None
    return row["user_id"] or ""


def map_user_id(incoming: str) -> str:
    """sl-{uuid} 归一（sl 侧自身即为 sl- 前缀；sm 侧映射 sm-）"""
    if not incoming:
        return ""
    return incoming
