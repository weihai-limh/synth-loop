"""select_system_prompt 工具实现"""

from typing import Any

import httpx

from ..config import get_section
from ..models.session import Session

# 工具定义
SELECT_SYSTEM_PROMPT_DEFINITION = {
    "type": "function",
    "function": {
        "name": "select_system_prompt",
        "description": "根据用户问题意图选择最合适的专家人设 prompt。",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "需要匹配意图的文本，通常是用户的第一句话或上下文。",
                }
            },
            "required": ["query"],
        },
    },
}


async def handle_select_system_prompt(
    session: Session, args: dict[str, Any]
) -> dict[str, Any]:
    """
    处理 select_system_prompt 工具调用

    Args:
        session: 当前会话
        args: 工具参数，包含 query 字段

    Returns:
        执行结果
    """
    query = args.get("query", "")

    # 获取配置
    prompt_config = get_section("prompt_service")
    prompt_service_url = prompt_config.get("url", "http://localhost:13156")
    default_system_prompt = prompt_config.get("default_system_prompt", "你是一个有帮助的AI助手。")

    try:
        # 调用 strata-match 服务
        async with httpx.AsyncClient(timeout=5) as client:
            response = await client.post(
                f"{prompt_service_url}/api/v1/query",
                json={"user_ask": query},
            )
            response.raise_for_status()
            data = response.json()

        prompt_text = data.get("primary_prompt", "")

        if prompt_text:
            session.permanent_system_prompt = prompt_text
            session.snapshot_dirty = True
            return {
                "status": "selected",
                "prompt_preview": prompt_text[:100] + "..." if len(prompt_text) > 100 else prompt_text,
            }
        else:
            # 无匹配结果，使用默认 Prompt
            session.permanent_system_prompt = default_system_prompt
            session.snapshot_dirty = True
            return {"status": "fallback", "prompt": "default"}

    except Exception as e:
        # 降级：使用默认 Prompt
        session.permanent_system_prompt = default_system_prompt
        session.snapshot_dirty = True
        return {"status": "error", "fallback": True, "message": str(e)}
