"""v0_1_1 Phase 4: Task REST API — 状态查询 + 取消"""
import logging
from typing import Any

import aiosqlite
from fastapi import APIRouter, HTTPException

from ..database import get_db_path, get_task

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/tasks", tags=["tasks"])


@router.get("/{task_id}", summary="Query task status")
async def get_task_status(task_id: str) -> dict[str, Any]:
    """仅返回状态，不含结果内容"""
    task = await get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail=f"Task not found: {task_id}")
    return {
        "id": task["id"],
        "status": task.get("status", "unknown"),
        "session_id": task.get("session_id"),
        "user_id": task.get("user_id"),
        "created_at": task.get("created_at"),
        "updated_at": task.get("updated_at"),
    }


@router.post("/{task_id}/cancel", summary="Cancel task")
async def cancel_task(task_id: str) -> dict[str, Any]:
    """取消任务——设置 status=cancelled"""
    db_path = get_db_path()
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute(
            "UPDATE tasks SET status = 'cancelled', updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (task_id,),
        )
        await db.commit()
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail=f"Task not found: {task_id}")

    logger.info(f"Task cancelled: {task_id}")
    return {"id": task_id, "status": "cancelled"}
