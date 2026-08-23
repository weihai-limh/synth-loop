"""健康检查路由"""

from fastapi import APIRouter

from ..database import get_active_session_count

router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check() -> dict:
    """
    健康检查端点

    Returns:
        服务状态信息
    """
    active_sessions = await get_active_session_count()
    return {
        "status": "ok",
        "version": "0.1.0",
        "active_sessions": active_sessions,
    }
