"""
StreamingHandler - Phase 3: GW-P7 SSE流式支持
检测 stream 参数；async generator 逐块返回，支持 OpenAI + Anthropic 双协议。
"""
import json
import logging
from typing import AsyncGenerator, Optional

import httpx

from ..config import get_section

logger = logging.getLogger(__name__)


class StreamingHandler:
    """SSE 流式处理器"""

    @staticmethod
    async def stream_openai(
        messages: list[dict],
        model: str,
        api_base: str,
        api_key: str,
        **kwargs,
    ) -> AsyncGenerator[str, None]:
        """
        OpenAI 格式 SSE 流式输出

        Yields:
            SSE 格式字符串："data: {...}\\n\\n" 和 "data: [DONE]\\n\\n"
        """
        payload = {"model": model, "messages": messages, "stream": True, **{k: v for k, v in kwargs.items() if v is not None}}
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

        async with httpx.AsyncClient(base_url=api_base, timeout=120) as client:
            async with client.stream("POST", "/chat/completions", json=payload, headers=headers) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if line is not None:
                        yield line + "\n"

    @staticmethod
    async def stream_anthropic(
        messages: list[dict],
        model: str,
        api_base: str,
        api_key: str,
        system: Optional[str] = None,
        **kwargs,
    ) -> AsyncGenerator[str, None]:
        """
        Anthropic 格式 SSE 流式输出

        Yields:
            Anthropic SSE 格式字符串
        """
        payload = {"model": model, "messages": messages, "stream": True, "max_tokens": kwargs.get("max_tokens", 1024)}
        if system:
            payload["system"] = system
        headers = {"x-api-key": api_key, "anthropic-version": "2023-06-01", "Content-Type": "application/json"}

        async with httpx.AsyncClient(base_url=api_base, timeout=120) as client:
            async with client.stream("POST", "/v1/messages", json=payload, headers=headers) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if line is not None:
                        yield line + "\n"

    @staticmethod
    async def stream_anthropic_translated(
        messages: list[dict],
        model: str,
        api_base: str,
        api_key: str,
        **kwargs,
    ) -> AsyncGenerator[str, None]:
        """
        OpenAI→Anthropic chunk 级 SSE 流式翻译 (A.6.2)
        包装下游 OpenAI SSE，逐 chunk 翻译为 Anthropic event 格式。
        """
        import time
        msg_id = f"msg_{int(time.time())}"
        model_name = model

        # message_start
        yield f'event: message_start\ndata: {{"type":"message_start","message":{{"id":"{msg_id}","type":"message","role":"assistant","model":"{model_name}","stop_reason":null,"stop_sequence":null,"content":[]}}}}\n\n'

        block_idx = 0
        started = False
        async for line in StreamingHandler.stream_openai(messages, model, api_base, api_key, **kwargs):
            if not line or line.strip() == "data: [DONE]":
                break
            if not line.startswith("data: "):
                continue
            try:
                chunk = json.loads(line[6:].strip())
            except json.JSONDecodeError:
                continue

            delta = (chunk.get("choices") or [{}])[0].get("delta", {})
            if "role" in delta:
                continue

            text = delta.get("content")
            if not text:
                continue

            if not started:
                yield f'event: content_block_start\ndata: {{"type":"content_block_start","index":{block_idx},"content_block":{{"type":"text"}}}}\n\n'
                started = True

            yield f'event: content_block_delta\ndata: {{"type":"content_block_delta","index":{block_idx},"delta":{{"type":"text_delta","text":{json.dumps(text)}}}}}\n\n'

        # 收尾事件
        if started:
            yield f'event: content_block_stop\ndata: {{"type":"content_block_stop","index":{block_idx}}}\n\n'
        yield f'event: message_delta\ndata: {{"type":"message_delta","delta":{{"stop_reason":"end_turn","stop_sequence":null}}}}\n\n'
        yield f'event: message_stop\ndata: {{"type":"message_stop"}}\n\n'
