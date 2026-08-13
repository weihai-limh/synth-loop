"""管道 API (v0_1_2 T7)

9 端点: 创建/计划确认/启动/查询/暂停恢复中止/路径确认/审批/驳回/相位查询
"""

import logging
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from ..models.pipeline import (
    PipelineSession, PlanConfig, PhaseConfig, PhaseStatus,
    PipelineGates, PipelineStatus,
)
from ..services.pipeline_lifecycle import PipelineLifecycleManager
from ..services.phase_executor import PhaseExecutor

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/pipelines", tags=["pipelines"])

# 服务实例（在注册路由时注入）
pipeline_manager = PipelineLifecycleManager()
phase_executor = PhaseExecutor()

# 内存存储（V0.1.2 临时——V0.1.3 迁移到共享 DB）
_pipelines: dict[str, PipelineSession] = {}


# ═══════════════════════════════════════════════════════════
# 1. POST /api/v1/pipelines — 创建管道
# ═══════════════════════════════════════════════════════════

@router.post("")
async def create_pipeline(request: Request) -> JSONResponse:
    """创建管道（status=draft）"""
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=422, detail="Invalid JSON body")

    user_ask = body.get("user_ask", "")
    plan_config_data = body.get("plan_config", {})
    pipeline_gates_data = body.get("pipeline_gates", {})

    if not plan_config_data.get("phases"):
        raise HTTPException(status_code=422, detail="plan_config.phases is required")

    # 构建 PlanConfig
    phases = [
        PhaseConfig(
            index=p["index"], name=p["name"], description=p.get("description", ""),
            mode=p.get("mode", "single_ai"), mode_params=p.get("mode_params"),
            gates=PipelineGates.from_dict(p.get("gates", {})),
        )
        for p in plan_config_data["phases"]
    ]
    plan_config = PlanConfig(phases=phases)
    pipeline_gates = PipelineGates.from_dict(pipeline_gates_data)

    session = await pipeline_manager.create_pipeline(
        intent=user_ask,
        plan_config=plan_config,
        user_id=body.get("user_id"),
        pipeline_gates=pipeline_gates,
    )

    _pipelines[session.pipeline_id] = session
    return JSONResponse(content=session.to_dict(), status_code=201)


# ═══════════════════════════════════════════════════════════
# 2. POST /api/v1/pipelines/{id}/plan-confirm — 计划确认门
# ═══════════════════════════════════════════════════════════

@router.post("/{pipeline_id}/plan-confirm")
async def plan_confirm(pipeline_id: str, request: Request) -> JSONResponse:
    """确认计划（管道级闸1）"""
    session = _get_pipeline(pipeline_id)
    try:
        body = await request.json()
    except Exception:
        body = {}

    if not body.get("confirmed", True):
        session.status = PipelineStatus.ABORTED
        return JSONResponse(content=session.to_dict())

    await pipeline_manager.confirm_plan(session)
    return JSONResponse(content=session.to_dict())


# ═══════════════════════════════════════════════════════════
# 3. POST /api/v1/pipelines/{id}/start — 执行启动门
# ═══════════════════════════════════════════════════════════

@router.post("/{pipeline_id}/start")
async def start_pipeline(pipeline_id: str, request: Request) -> JSONResponse:
    """启动管道（管道级闸2）"""
    session = _get_pipeline(pipeline_id)
    try:
        body = await request.json()
    except Exception:
        body = {}

    if session.status != PipelineStatus.DRAFT:
        raise HTTPException(status_code=409, detail=f"Cannot start: pipeline is {session.status}")

    await pipeline_manager.start(session)
    return JSONResponse(content=session.to_dict())


# ═══════════════════════════════════════════════════════════
# 4. GET /api/v1/pipelines/{id} — 查询管道
# ═══════════════════════════════════════════════════════════

@router.get("/{pipeline_id}")
async def get_pipeline(pipeline_id: str) -> JSONResponse:
    """查询管道完整状态"""
    session = _get_pipeline(pipeline_id)
    return JSONResponse(content=session.to_dict())


# ═══════════════════════════════════════════════════════════
# 5. PATCH /api/v1/pipelines/{id} — 暂停/恢复/中止
# ═══════════════════════════════════════════════════════════

@router.patch("/{pipeline_id}")
async def patch_pipeline(pipeline_id: str, request: Request) -> JSONResponse:
    """暂停/恢复/中止管道"""
    session = _get_pipeline(pipeline_id)
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=422, detail="Invalid JSON body")

    action = body.get("action", "")
    reason = body.get("reason", "")

    if action == "pause":
        await pipeline_manager.pause(session, reason)
    elif action == "resume":
        await pipeline_manager.resume(session)
    elif action == "abort":
        await pipeline_manager.abort(session, reason)
    else:
        raise HTTPException(status_code=422, detail=f"Unknown action: {action}")

    return JSONResponse(content=session.to_dict())


# ═══════════════════════════════════════════════════════════
# 6. POST /api/v1/pipelines/{id}/phases/{n}/path-confirm — 闸2
# ═══════════════════════════════════════════════════════════

@router.post("/{pipeline_id}/phases/{phase_index}/path-confirm")
async def path_confirm(pipeline_id: str, phase_index: int, request: Request) -> JSONResponse:
    """闸2: 确认路径 JSON"""
    session = _get_pipeline(pipeline_id)
    try:
        body = await request.json()
    except Exception:
        body = {}

    confirmed = body.get("confirmed", True)
    edits = body.get("edits")

    await phase_executor.confirm_path(session, phase_index, confirmed, edits)
    return JSONResponse(content=session.to_dict())


# ═══════════════════════════════════════════════════════════
# 7. POST /api/v1/pipelines/{id}/phases/{n}/approve — 闸3
# ═══════════════════════════════════════════════════════════

@router.post("/{pipeline_id}/phases/{phase_index}/approve")
async def approve_phase(pipeline_id: str, phase_index: int) -> JSONResponse:
    """闸3: 审批通过"""
    session = _get_pipeline(pipeline_id)
    await phase_executor.approve_phase(session, phase_index)
    return JSONResponse(content=session.to_dict())


# ═══════════════════════════════════════════════════════════
# 8. POST /api/v1/pipelines/{id}/phases/{n}/reject — 闸3驳回
# ═══════════════════════════════════════════════════════════

@router.post("/{pipeline_id}/phases/{phase_index}/reject")
async def reject_phase(pipeline_id: str, phase_index: int, request: Request) -> JSONResponse:
    """闸3: 驳回"""
    session = _get_pipeline(pipeline_id)
    try:
        body = await request.json()
    except Exception:
        body = {}

    feedback = body.get("feedback", "no feedback provided")
    await phase_executor.reject_phase(session, phase_index, feedback)
    return JSONResponse(content=session.to_dict())


# ═══════════════════════════════════════════════════════════
# 9. GET /api/v1/pipelines/{id}/phases/{n} — 相位详情
# ═══════════════════════════════════════════════════════════

@router.get("/{pipeline_id}/phases/{phase_index}")
async def get_phase_detail(pipeline_id: str, phase_index: int) -> JSONResponse:
    """查询相位详情"""
    session = _get_pipeline(pipeline_id)
    if phase_index < 0 or phase_index >= len(session.phases):
        raise HTTPException(status_code=404, detail=f"Phase {phase_index} not found")

    phase = session.phases[phase_index]
    phase_gates = [g.to_dict() for g in session.quality_gates if g.phase_index == phase_index]

    return JSONResponse(content={
        "phase": phase.to_dict(),
        "quality_gates": phase_gates,
    })


# ═══════════════════════════════════════════════════════════
# 工具函数
# ═══════════════════════════════════════════════════════════

def _get_pipeline(pipeline_id: str) -> PipelineSession:
    """获取管道，不存在时抛 404"""
    session = _pipelines.get(pipeline_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"Pipeline {pipeline_id} not found")
    return session
