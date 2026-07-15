"""Mock 下游 LLM 服务，用于开发阶段"""

import json
import logging
import uuid
from typing import Optional

logger = logging.getLogger(__name__)


class MockDownstreamLLM:
    """Mock 下游 LLM 服务"""
    
    def __init__(self):
        logger.info("MockDownstreamLLM 初始化")
    
    async def chat(
        self,
        messages: list,
        model: str = None,
        tools: list = None,
        api_key: str = None,
        **kwargs
    ) -> dict:
        """模拟 LLM 调用"""
        logger.info(f"MockDownstreamLLM.chat: model={model}, messages_count={len(messages)}")
        
        # 获取用户消息
        user_message = self._get_user_message(messages)
        
        # 如果有工具，模拟工具调用
        if tools and self._should_call_tool(user_message):
            return self._mock_tool_call_response(tools, user_message)
        
        # 否则返回普通响应
        return self._mock_text_response(user_message)
    
    def _get_user_message(self, messages: list) -> str:
        """从消息列表中提取用户消息"""
        for msg in reversed(messages):
            if msg.get("role") == "user":
                content = msg.get("content", "")
                if isinstance(content, str):
                    return content
                elif isinstance(content, list):
                    # 处理多模态内容
                    text_parts = [item.get("text", "") for item in content if item.get("type") == "text"]
                    return " ".join(text_parts)
        return ""
    
    def _should_call_tool(self, user_message: str) -> bool:
        """判断是否应该调用工具"""
        user_message_lower = user_message.lower()
        
        # 数学计算相关
        if any(keyword in user_message_lower for keyword in ["计算", "算", "面积", "体积", "公式", "数学"]):
            return True
        
        # 查询能力相关
        if any(keyword in user_message_lower for keyword in ["能力", "指令", "功能", "能做什么"]):
            return True
        
        return False
    
    def _mock_tool_call_response(self, tools: list, user_message: str) -> dict:
        """模拟工具调用响应"""
        # 选择要调用的工具
        tool_name = self._select_tool(tools, user_message)
        
        # 构建工具调用参数
        arguments = self._build_tool_arguments(tool_name, user_message)
        
        return {
            "id": f"chatcmpl-{uuid.uuid4().hex[:8]}",
            "object": "chat.completion",
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": f"call_{uuid.uuid4().hex[:8]}",
                                "type": "function",
                                "function": {
                                    "name": tool_name,
                                    "arguments": json.dumps(arguments, ensure_ascii=False)
                                }
                            }
                        ]
                    },
                    "finish_reason": "tool_calls"
                }
            ],
            "usage": {
                "prompt_tokens": 100,
                "completion_tokens": 50,
                "total_tokens": 150
            }
        }
    
    def _select_tool(self, tools: list, user_message: str) -> str:
        """选择要调用的工具"""
        user_message_lower = user_message.lower()
        
        # 检查是否有 discover_textcli 工具
        tool_names = [t.get("function", {}).get("name", "") for t in tools]
        
        # 查询能力相关
        if any(keyword in user_message_lower for keyword in ["能力", "指令", "功能", "能做什么"]):
            if "discover_textcli" in tool_names:
                return "discover_textcli"
        
        # 数学计算相关
        if any(keyword in user_message_lower for keyword in ["计算", "算", "面积", "体积", "公式", "数学"]):
            if "call_textcli" in tool_names:
                return "call_textcli"
        
        # 默认使用第一个工具
        return tool_names[0] if tool_names else "unknown"
    
    def _build_tool_arguments(self, tool_name: str, user_message: str) -> dict:
        """构建工具调用参数"""
        if tool_name == "discover_textcli":
            # 提取关键词
            keywords = self._extract_keywords(user_message)
            return {"query": keywords}
        
        elif tool_name == "call_textcli":
            # 构建 text-cli 指令
            prompt = self._build_textcli_prompt(user_message)
            return {"prompt": prompt}
        
        return {}
    
    def _extract_keywords(self, user_message: str) -> str:
        """提取关键词"""
        user_message_lower = user_message.lower()
        
        if any(keyword in user_message_lower for keyword in ["数学", "计算", "算"]):
            return "数学"
        if any(keyword in user_message_lower for keyword in ["时间", "日期"]):
            return "时间"
        if any(keyword in user_message_lower for keyword in ["文件", "读取"]):
            return "文件"
        
        return ""
    
    def _build_textcli_prompt(self, user_message: str) -> str:
        """构建 text-cli 指令"""
        user_message_lower = user_message.lower()
        
        # 数学计算
        if "面积" in user_message_lower and "圆" in user_message_lower:
            return "AI:tc-math;eval,pi * 5 ** 2"
        if "面积" in user_message_lower:
            return "AI:tc-math;eval,10 * 20"
        if "计算" in user_message_lower:
            return "AI:tc-math;eval,1 + 1"
        
        return "AI:text-cli;query,compact"
    
    def _mock_text_response(self, user_message: str) -> dict:
        """模拟文本响应"""
        # 根据用户消息生成响应
        response_text = self._generate_response(user_message)
        
        return {
            "id": f"chatcmpl-{uuid.uuid4().hex[:8]}",
            "object": "chat.completion",
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": response_text
                    },
                    "finish_reason": "stop"
                }
            ],
            "usage": {
                "prompt_tokens": 100,
                "completion_tokens": 50,
                "total_tokens": 150
            }
        }
    
    def _generate_response(self, user_message: str) -> str:
        """生成响应文本"""
        user_message_lower = user_message.lower()
        
        if "你好" in user_message_lower or "hello" in user_message_lower:
            return "你好！我是 Mock LLM 助手，很高兴为你服务。"
        
        if "帮助" in user_message_lower or "help" in user_message_lower:
            return "我可以帮助你进行各种任务，包括数学计算、编程、写作等。请告诉我你需要什么帮助。"
        
        return f"这是 Mock LLM 的响应。你刚才说的是：{user_message}"


# 全局实例
_mock_downstream_llm: Optional[MockDownstreamLLM] = None


def get_mock_downstream_llm() -> MockDownstreamLLM:
    """获取 MockDownstreamLLM 单例"""
    global _mock_downstream_llm
    if _mock_downstream_llm is None:
        _mock_downstream_llm = MockDownstreamLLM()
    return _mock_downstream_llm
