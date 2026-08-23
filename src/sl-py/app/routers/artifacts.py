"""_a P4.3: 数据面下行端点——GET /v1/artifacts/{id} + ?pipeline_id="""

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from ..services.artifact_dataplane import get_artifact, list_pipeline_artifacts

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/artifacts", tags=["artifacts"])


@router.get("/{artifact_id}", summary="获取产物详情")
async def fetch_artifact(artifact_id: str) -> dict[str, Any]:
    artifact = await get_artifact(artifact_id)
    if artifact is None:
        raise HTTPException(status_code=404, detail=f"Artifact not found: {artifact_id}")
    return artifact


@router.get("", summary="按管道列出产物（时间线）")
async def list_artifacts(pipeline_id: str = Query(..., description="管道 ID")) -> dict[str, Any]:
    items = await list_pipeline_artifacts(pipeline_id)
    return {"pipeline_id": pipeline_id, "items": items, "total": len(items)}
