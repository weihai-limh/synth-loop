"""_c: 永久区通道端点——GET/POST/DELETE /v1/longdata（doc/memory 引入、删除、列出）"""

import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..services.longdata import add_longdata, del_longdata, list_longdata, VALID_LONGDATA_TYPES

logger = logging.getLogger(__name__)


def _get_session_manager():
    """延迟 import chat.session_manager——确保拿到 init_services 已初始化的实例（避免模块加载时未初始化）。"""
    from .chat import session_manager
    return session_manager

router = APIRouter(prefix="/v1/longdata", tags=["longdata"])


class LongDataAddRequest(BaseModel):
    """add 请求体"""
    session_id: str
    type: str           # "doc" | "memory"
    content: str


class LongDataDelRequest(BaseModel):
    """del 请求体（按内部 id + session_id）"""
    session_id: str
    id: str


@router.post("", summary="引入 doc/memory 到永久区")
async def longdata_add(req: LongDataAddRequest) -> dict[str, Any]:
    if req.type not in VALID_LONGDATA_TYPES:
        raise HTTPException(status_code=400,
                            detail=f"invalid type: {req.type}, valid: {list(VALID_LONGDATA_TYPES)}")
    sm = _get_session_manager()
    session = await sm.get_or_create(req.session_id)
    result = await add_longdata(session, req.session_id, req.type, req.content)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.delete("/{id}", summary="按内部 id 删除永久区 longdata")
async def longdata_del(id: str, session_id: str) -> dict[str, Any]:
    sm = _get_session_manager()
    session = await sm.get_or_create(session_id)
    result = await del_longdata(session, session_id, id)
    return result


@router.get("", summary="列出会话永久区 longdata")
async def longdata_list(session_id: str) -> dict[str, Any]:
    return await list_longdata(session_id)
