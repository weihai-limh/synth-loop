"""
Packets 路由 - Phase 6: GW-P8 POST /v1/packets 数据面端点
"""
import logging

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from ..config import get_packets_settings
from ..services.packet_store import PacketStore, VALID_PACKET_TYPES, get_packet_store

logger = logging.getLogger(__name__)

router = APIRouter(tags=["packets"])

# ── 请求模型 ──


class PacketSubmitRequest(BaseModel):
    source: str
    type: str
    payload: dict = Field(default_factory=dict)
    meta: dict = Field(default_factory=dict)


class PacketSubmitResponse(BaseModel):
    packet_id: str


# ── 端点 ──


@router.post("/v1/packets", response_model=PacketSubmitResponse)
async def submit_packet(request: PacketSubmitRequest, http_request: Request):
    """
    提交上下文数据包

    - 校验必填字段、type 合法性、体积上限
    - 存入 PacketStore，返回 packet_id
    """
    settings = get_packets_settings()

    # 总开关
    if not settings.enabled:
        raise HTTPException(status_code=503, detail="Packets API is disabled")

    store = get_packet_store()

    # type 校验
    if not PacketStore.validate_type(request.type):
        logger.warning(f"Unknown packet type: {request.type}")
        raise HTTPException(
            status_code=400,
            detail=f"Unknown packet type: '{request.type}'. "
                   f"Valid types: {', '.join(sorted(VALID_PACKET_TYPES))}"
        )

    # 体积检查
    try:
        body_bytes = await http_request.body()
        size_mb = len(body_bytes) / (1024 * 1024)
        if size_mb > settings.max_packet_size_mb:
            raise HTTPException(
                status_code=413,
                detail=f"Packet too large: {size_mb:.1f}MB > {settings.max_packet_size_mb}MB"
            )
    except HTTPException:
        raise
    except Exception:
        logger.debug("Packet body() already consumed, skipping precise size check")

    packet = store.store(
        source=request.source,
        ptype=request.type,
        payload=request.payload,
        meta=request.meta or {},
    )

    logger.info(
        f"Packet submitted: {packet.packet_id} "
        f"(source={request.source}, type={request.type})"
    )
    return PacketSubmitResponse(packet_id=packet.packet_id)
