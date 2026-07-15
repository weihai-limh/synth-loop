"""call_textcli 工具：调用 text-cli 指令执行操作"""

import logging

from ..services.textcli_client import get_textcli_client

logger = logging.getLogger(__name__)


async def handle_call_textcli(session, args: dict) -> dict:
    """处理 call_textcli 工具调用"""
    prompt = args.get("prompt", "")
    endpoint = args.get("endpoint", None)
    
    logger.info(f"handle_call_textcli: prompt={prompt}, endpoint={endpoint}")
    
    if not prompt:
        return {"status": "error", "message": "prompt 参数不能为空"}
    
    # 验证指令格式
    if not prompt.startswith("AI:"):
        return {"status": "error", "message": "指令格式错误，必须以 'AI:' 开头"}
    
    # 调用 text-cli
    try:
        textcli_client = get_textcli_client()
        result = await textcli_client.call(prompt, endpoint)
        
        # 提取结果
        rst_types = result.get("rst_types", "")
        rst_data = result.get("rst_data", {})
        
        logger.info(f"handle_call_textcli 成功: rst_types={rst_types}")
        
        return {
            "status": "success",
            "rst_types": rst_types,
            "rst_data": rst_data
        }
    except Exception as e:
        logger.error(f"handle_call_textcli 失败: {e}")
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
                "endpoint": {
                    "type": "string",
                    "description": "可选，节点地址，默认自动路由"
                }
            },
            "required": ["prompt"]
        }
    }
}
