"""_c: 永久区通道（/v1/longdata）——doc/memory 引入、删除、列出。

数据面通道B（永久区）：doc/memory 经此引入，落 longdata 表 + 会话永久区。
- add: 通用文本处理 → 写 longdata 表（生成内部 id）→ 落永久区（doc→loaded_docs；memory→permanent_system_prompt+`<user-memory>`包裹）
- del: 按内部 id + session_id 双重校验 → 删表 → 从永久区移除
- list: 按 session_id 列出

id 语义（两层）：对外只需会话 id；内部 add 生成内部 id 入库（等价 loaded_docs.doc_id），del 按内部 id 精确删。
"""

import logging
import time
from typing import Any, Optional
from uuid import uuid4

from ..database import get_shared_db

logger = logging.getLogger(__name__)

# 永久区类型（写死，不扩 config）
VALID_LONGDATA_TYPES = ("doc", "memory")


def _normalize_text(text: str) -> str:
    """通用文本处理：去首尾空白、压缩连续空行。"""
    lines = [ln.strip() for ln in text.splitlines()]
    result = []
    prev_blank = False
    for ln in lines:
        if not ln.strip():
            if not prev_blank:
                result.append("")
            prev_blank = True
        else:
            result.append(ln)
            prev_blank = False
    return "\n".join(result).strip()


async def _insert_longdata(lid: str, session_id: str, type_: str, content: str) -> None:
    db = await get_shared_db()
    await db.execute(
        "INSERT INTO longdata (id, session_id, type, content, created_at) VALUES (?, ?, ?, ?, ?)",
        (lid, session_id, type_, content, time.time()),
    )
    await db.commit()


async def _get_longdata(lid: str) -> Optional[dict]:
    db = await get_shared_db()
    cursor = await db.execute(
        "SELECT id, session_id, type, content, created_at FROM longdata WHERE id = ?", (lid,))
    row = await cursor.fetchone()
    return dict(row) if row else None


async def _delete_longdata(lid: str) -> None:
    db = await get_shared_db()
    await db.execute("DELETE FROM longdata WHERE id = ?", (lid,))
    await db.commit()


async def _list_longdata_by_session(session_id: str) -> list[dict]:
    db = await get_shared_db()
    cursor = await db.execute(
        "SELECT id, session_id, type, content, created_at FROM longdata "
        "WHERE session_id = ? ORDER BY created_at", (session_id,))
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def add_longdata(session: Any, session_id: str, type_: str, content: str) -> dict:
    """引入 doc/memory 到指定会话永久区。接收 session 对象（由路由层经 session_manager 获取）。"""
    if type_ not in VALID_LONGDATA_TYPES:
        return {"error": f"invalid type: {type_}", "valid_types": list(VALID_LONGDATA_TYPES)}
    if not content or not content.strip():
        return {"error": "content required"}

    content = _normalize_text(content)
    lid = f"ld_{uuid4().hex[:12]}"

    # 1. 写 longdata 表
    await _insert_longdata(lid, session_id, type_, content)

    # 2. 落永久区
    if type_ == "doc":
        session.loaded_docs.append({"doc_id": lid, "content": content})
    elif type_ == "memory":
        block = f"<user-memory>{content}</user-memory>"
        session.permanent_system_prompt = (
            session.permanent_system_prompt + "\n" + block
            if session.permanent_system_prompt else block
        )
    session.snapshot_dirty = True

    return {"id": lid}


async def del_longdata(session: Any, session_id: str, lid: str) -> dict:
    """按内部 id + session_id 双重校验删除。"""
    row = await _get_longdata(lid)
    if not row or row["session_id"] != session_id:
        return {"deleted": False}

    # 1. 删 longdata 表
    await _delete_longdata(lid)

    # 2. 从会话永久区移除
    if row["type"] == "doc":
        session.loaded_docs = [d for d in session.loaded_docs if d.get("doc_id") != lid]
    elif row["type"] == "memory":
        block = f"<user-memory>{row['content']}</user-memory>"
        session.permanent_system_prompt = session.permanent_system_prompt.replace(block, "")
    session.snapshot_dirty = True

    return {"deleted": True}


async def list_longdata(session_id: str) -> dict:
    """按会话 id 列出该会话永久区的 longdata。"""
    items = await _list_longdata_by_session(session_id)
    return {"session_id": session_id, "items": items}
