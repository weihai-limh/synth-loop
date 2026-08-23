"""_a P2.1: 运行时表管理 API（CRUD，token 脱敏）

鉴权：_a 统一 token 后（3.12）管理 API 要求 admin scope（x-synthloop-token scope=admin，
普通 user/service token → 403）——"能改端点的人 ≠ 能聊天的人"。
默认内网无鉴权（auth.enabled=false）；生产开 auth 后 CRUD 强制校验（运行时表含 token，
是唯一值得上鉴权的管理面）。
"""

import logging
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Request

from ..config import get_auth_settings
from ..services.runtime_endpoints import (
    create_endpoint,
    delete_endpoint,
    list_endpoints,
    update_endpoint,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/runtime-endpoints", tags=["runtime-endpoints"])

TOKEN_HEADER = "x-synthloop-token"


async def _require_admin(request: Request) -> None:
    """admin scope 校验（auth.enabled=true 时生效；默认内网无鉴权）"""
    auth = get_auth_settings()
    if not auth.enabled:
        return
    token = request.headers.get(TOKEN_HEADER)
    if not token:
        raise HTTPException(status_code=401, detail="Missing x-synthloop-token header")
    from ..services.token_service import verify_token
    user_id = await verify_token("sl", token, "admin")
    if user_id is None:
        raise HTTPException(status_code=403, detail="admin scope required")


@router.get("", summary="列出运行时端点（token 脱敏）")
async def list_runtime_endpoints() -> dict[str, Any]:
    endpoints = await list_endpoints()
    return {"items": endpoints, "total": len(endpoints)}


@router.post("", summary="添加运行时端点")
async def add_runtime_endpoint(request: Request, body: dict[str, Any]) -> dict[str, Any]:
    await _require_admin(request)
    required = ("alias", "url")
    for key in required:
        if key not in body or not body[key]:
            raise HTTPException(status_code=422, detail=f"缺少必填字段: {key}")
    return await create_endpoint(body)


@router.patch("/{alias}", summary="修改运行时端点（url/token/rank/is_active）")
async def patch_runtime_endpoint(alias: str, request: Request, body: dict[str, Any]) -> dict[str, Any]:
    await _require_admin(request)
    updated = await update_endpoint(alias, body)
    if updated is None:
        raise HTTPException(status_code=404, detail=f"端点不存在: {alias}")
    return updated


@router.delete("/{alias}", summary="删除运行时端点")
async def delete_runtime_endpoint(alias: str, request: Request) -> dict[str, Any]:
    await _require_admin(request)
    ok = await delete_endpoint(alias)
    if not ok:
        raise HTTPException(status_code=404, detail=f"端点不存在: {alias}")
    return {"status": "ok", "deleted": alias}
