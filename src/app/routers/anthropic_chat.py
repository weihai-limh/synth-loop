"""Anthropic 格式的聊天接口"""

import json
import logging
import re
import time
from typing import Any, Optional

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ..config import get_section, load_config, get_packets_settings
from ..database import get_task
from ..services.protocol_translator import get_request_translator, get_response_translator
from ..services.downstream_llm import get_downstream_llm
from ..services.streaming_handler import StreamingHandler
from ..services.packet_store import get_packet_store
from ..services.preprocessors import preprocess_packet

logger = logging.getLogger(__name__)

router = APIRouter(tags=["anthropic"])

# v0_1_1 Phase 2: Task-ID 正则（Anthropic 入口）
_TASK_ID_PATTERN = re.compile(r"Task-(.+?)-synthloop")


def _extract_anthropic_user_text(messages: list[dict[str, Any]]) -> str:
    """从 Anthropic messages 中提取最后一条 user 消息文本"""
    for msg in reversed(messages):
        if msg.get("role") == "user":
            content = msg.get("content", "")
            if isinstance(content, list):
                # Anthropic content 可能是 [{"type": "text", "text": "..."}, ...]
                parts = [b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"]
                return " ".join(parts)
            return str(content)
    return ""


async def _anthropic_task_id_check(user_text: str) -> dict | None:
    """Anthropic 入口的 Task-ID 前置检查"""
    match = _TASK_ID_PATTERN.search(user_text)
    if not match:
        return None

    full_id = match.group(0)
    task = await get_task(full_id)
    if task:
        status = task.get("status", "unknown")
        if status == "completed":
            text = task.get("result", "") or "Task completed."
        elif status in ("failed", "cancelled"):
            text = task.get("error", "") or f"Task {status}."
        elif status in ("queued", "running"):
            text = f"Task is {status}. Please check later."
        else:
            text = f"Task status: {status}"
    else:
        text = "Task not found."

    return {
        "id": f"msg_{full_id}",
        "type": "message",
        "role": "assistant",
        "content": [{"type": "text", "text": text}],
        "model": "pre-check",
        "stop_reason": "end_turn",
        "usage": {"input_tokens": 0, "output_tokens": 0},
    }


class AnthropicMessageRequest(BaseModel):
    """Anthropic 消息请求格式"""
    model: str
    messages: list[dict[str, Any]]
    max_tokens: int = 1024
    system: Optional[str] = None
    temperature: Optional[float] = None
    top_p: Optional[float] = None
    stop_sequences: Optional[list[str]] = None
    stream: Optional[bool] = False
    tools: Optional[list[dict[str, Any]]] = None
    tool_choice: Optional[dict[str, Any]] = None
    # v0_1_1 Phase 6: packets 数据面
    packets: Optional[list[str]] = None
    inline_data: Optional[list[dict[str, Any]]] = None


async def _inject_anthropic_packets(request) -> tuple[str | None, list[str]]:
    """
    Anthropic 入口的 packets 上下文注入（与 chat.py _inject_packets 逻辑一致）
    """
    packets_config = get_packets_settings()
    if not packets_config.enabled:
        return None, []

    summaries: list[str] = []
    expired_ids: list[str] = []

    # packets[]
    packet_ids = getattr(request, "packets", None)
    if packet_ids:
        if len(packet_ids) > packets_config.max_packets_per_request:
            packet_ids = packet_ids[:packets_config.max_packets_per_request]
        try:
            store = get_packet_store()
            valid_packets, expired = store.get_batch(packet_ids)
            expired_ids = expired
            for pkt in valid_packets:
                try:
                    text = preprocess_packet(pkt)
                    if text:
                        summaries.append(f"[{pkt.type}/{pkt.source}] {text}")
                except Exception:
                    logger.warning(f"Packet preprocessing skipped: {pkt.packet_id}")
        except Exception as e:
            logger.warning(f"PacketStore exception: {e}")

    # inline_data[]
    inline_list = getattr(request, "inline_data", None)
    if inline_list:
        if len(inline_list) > packets_config.max_inline_data_per_request:
            inline_list = inline_list[:packets_config.max_inline_data_per_request]
        for item in inline_list:
            ptype = item.get("type", "unknown")
            payload_str = str(item.get("payload", {}))
            if len(payload_str) > 5 * 1024 * 1024:
                summaries.append("[skipped_oversize]")
                continue
            if len(payload_str) <= 200:
                summaries.append(f"[inline:{ptype}] {payload_str}")
            else:
                summaries.append(f"[inline:{ptype}] {payload_str[:200]}...")

    if not summaries:
        return None, expired_ids
    if expired_ids:
        logger.info(f"Expired packet IDs: {expired_ids}")
    context_text = "[上下文数据包]\n" + "\n".join(summaries)
    return context_text, expired_ids


@router.post("/v1/messages")
async def messages(
    request: AnthropicMessageRequest,
    x_api_key: Optional[str] = Header(None, alias="x-api-key"),
    anthropic_version: Optional[str] = Header(None, alias="anthropic-version"),
) -> Any:
    """
    Anthropic 格式的消息接口
    
    接收 Anthropic 格式的请求，转换为内部格式处理后返回 Anthropic 格式的响应。
    """
    logger.info(f"Received Anthropic-format request: model={request.model}, stream={request.stream}")
    
    try:
        # 1. 转换请求格式
        request_translator = get_request_translator()
        openai_request = request_translator.anthropic_to_openai(request.model_dump())

        # 1.2 v0_1_1 Phase 2: Anthropic 入口消息前置检查 (Task-ID)
        anthropic_user_text = _extract_anthropic_user_text(request.messages)
        task_check_result = await _anthropic_task_id_check(anthropic_user_text)
        if task_check_result is not None:
            logger.info(f"Anthropic Task-ID check: {anthropic_user_text[:50]}")
            return task_check_result

        downstream_llm = get_downstream_llm()
        llm_config = get_section("downstream_llm")
        api_key = x_api_key or llm_config.get("api_key", "")

        # 1.5 Anthropic 模型名 → 下游模型名映射
        cfg = load_config()
        model_map = cfg.get("anthropic_model_map", {})
        models = model_map.get("models", {})
        default_model = model_map.get("default", downstream_llm.default_model)
        resolved_model = models.get(request.model, default_model)

        # 1.6 v0_1_1 Phase 6: packets 上下文注入
        packets_context, _ = _inject_anthropic_packets(request)
        if packets_context and openai_request:
            openai_request["messages"].insert(0, {"role": "system", "content": packets_context})

        # 2. 流式分支（Phase 5 hotfix: 使用 Anthropic SSE 翻译器）
        if request.stream:
            handler = StreamingHandler()
            if openai_request is None or not openai_request.get("messages"):
                raise HTTPException(status_code=400, detail="Anthropic-to-OpenAI translation failed: empty messages")
            return StreamingResponse(
                handler.stream_anthropic_translated(
                    messages=openai_request.get("messages", []),
                    model=resolved_model,
                    api_base=downstream_llm.api_base,
                    api_key=api_key,
                ),
                media_type="text/event-stream",
            )

        # 3. 非流式调用下游 LLM
        openai_response = await downstream_llm.chat(
            messages=openai_request.get("messages", []),
            model=resolved_model,
            tools=openai_request.get("tools"),
            temperature=openai_request.get("temperature"),
            max_tokens=openai_request.get("max_tokens"),
        )
        
        # 4. 转换响应格式
        response_translator = get_response_translator()
        anthropic_response = response_translator.openai_to_anthropic(openai_response)
        
        logger.info(f"Anthropic response: stop_reason={anthropic_response.get('stop_reason')}")
        
        return anthropic_response
        
    except Exception as e:
        logger.error(f"Anthropic request processing failed: {e}")
        raise HTTPException(
            status_code=500,
            detail={
                "type": "error",
                "error": {
                    "type": "api_error",
                    "message": str(e)
                }
            }
        )


@router.post("/v1/messages/stream")
async def messages_stream(
    request: AnthropicMessageRequest,
    x_api_key: Optional[str] = Header(None, alias="x-api-key"),
    anthropic_version: Optional[str] = Header(None, alias="anthropic-version"),
) -> Any:
    """
    Anthropic 格式的消息流式接口
    
    注意：流式响应需要特殊处理，这里先返回不支持的提示。
    """
    raise HTTPException(
        status_code=501,
        detail={
            "type": "error",
            "error": {
                "type": "not_supported",
                "message": "Streaming is not yet supported. Use /v1/messages for non-streaming requests."
            }
        }
    )
