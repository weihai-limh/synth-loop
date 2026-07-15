"""v0_1_1 Phase 3: auth 中间件 — x-synthloop-user-id 校验"""
import logging
import time
from typing import Optional

import aiosqlite
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from ..config import get_auth_settings, get_section
from ..database import get_db_path

logger = logging.getLogger(__name__)

USER_HEADER = "x-synthloop-user-id"
CACHE_TTL = 300  # 5 分钟


class AuthMiddleware(BaseHTTPMiddleware):
    """用户认证中间件 — 三层行为（enabled/required 组合）"""

    def __init__(self, app):
        super().__init__(app)
        # 会话级缓存: {user_id: timestamp}
        self._cache: dict[str, float] = {}

    async def dispatch(self, request: Request, call_next):
        settings = get_auth_settings()

        # enabled=false → 完全跳过（零开销）
        if not settings.enabled:
            return await call_next(request)

        user_id = request.headers.get(USER_HEADER)

        # enabled=true, required=false, 无 Header → 放行
        if not user_id:
            if settings.required:
                return JSONResponse(
                    status_code=401,
                    content={"error": "Missing x-synthloop-user-id header"},
                )
            return await call_next(request)

        # 有 Header → 校验用户
        if not await self._validate_user(user_id):
            return JSONResponse(
                status_code=401,
                content={"error": f"Invalid or disabled user: {user_id}"},
            )

        # 校验通过 → 注入 user_id 到 request.state
        request.state.synthloop_user_id = user_id
        return await call_next(request)

    async def _validate_user(self, user_id: str) -> bool:
        """校验用户是否存在且启用"""
        # 缓存命中
        cached_at = self._cache.get(user_id)
        if cached_at and (time.time() - cached_at < CACHE_TTL):
            return True

        # 查 users 表
        db_path = get_db_path()
        try:
            async with aiosqlite.connect(db_path) as db:
                db.row_factory = aiosqlite.Row
                cursor = await db.execute(
                    "SELECT id, enabled FROM users WHERE id = ?",
                    (user_id,),
                )
                row = await cursor.fetchone()
                if row and row["enabled"]:
                    self._cache[user_id] = time.time()
                    return True
        except Exception as e:
            logger.error(f"Auth middleware DB query failed: {e}")

        return False
