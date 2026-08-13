"""call_textcli 工具：调用 text-cli 指令执行操作（_a：走强化客户端）"""

import logging

from ..services.textcli_enhanced_client import get_enhanced_client

logger = logging.getLogger(__name__)


async def handle_call_textcli(session, args: dict) -> dict:
    """处理 call_textcli 工具调用"""
    prompt = args.get("prompt", "")
    alias = args.get("endpoint_alias", None) or args.get("alias", None)

    logger.info(f"handle_call_textcli: prompt={prompt}, alias={alias}")

    if not prompt:
        return {"status": "error", "message": "prompt parameter cannot be empty"}

    # 验证指令格式（3.4 前缀校验透传）
    if not prompt.startswith("AI:"):
        return {"status": "error", "message": "Invalid instruction format, must start with 'AI:'"}

    # 调用 text-cli（强化客户端：alias 路由 + 令牌注入 + rank 降级）
    try:
        client = get_enhanced_client()
        result = await client.call(prompt, alias=alias)

        logger.info(f"handle_call_textcli succeeded: rst_types=text")

        return {
            "status": "success",
            "rst_types": "text",
            "rst_data": result.data,
            "rst_err": result.rst_err,
        }
    except Exception as e:
        logger.error(f"handle_call_textcli failed: {e}")
        return {"status": "error", "message": str(e)}


# 工具定义
CALL_TEXTCLI_DEFINITION = {
    "type": "function",
    "function": {
        "name": "call_textcli",
        "description": "调用 text-cli 指令执行操作",
        "parameters": {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "text-cli 指令，格式：AI:域;动作,参数"
                },
                "endpoint_alias": {
                    "type": "string",
                    "description": "可选，逻辑端点名（运行时表 alias），默认路由至 default_alias"
                }
            },
            "required": ["prompt"]
        }
    }
}
