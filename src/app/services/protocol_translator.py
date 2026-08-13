"""协议转译器：支持 OpenAI 和 Anthropic 格式互转"""

import json
import logging
import time
import uuid
from typing import Any, Optional

logger = logging.getLogger(__name__)


class RequestTranslator:
    """请求格式转译器"""
    
    @staticmethod
    def anthropic_to_openai(anthropic_request: dict[str, Any]) -> dict[str, Any]:
        """
        将 Anthropic 请求格式转换为 OpenAI 格式
        
        Anthropic 格式:
        {
            "model": "claude-3-opus-20240229",
            "max_tokens": 1024,
            "system": "You are a helpful assistant.",
            "messages": [
                {"role": "user", "content": "Hello"}
            ]
        }
        
        OpenAI 格式:
        {
            "model": "gpt-4",
            "messages": [
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": "Hello"}
            ],
            "max_tokens": 1024
        }
        """
        openai_request = {
            "model": anthropic_request.get("model", ""),
            "messages": [],
            "max_tokens": anthropic_request.get("max_tokens", 1024),
        }
        
        # 转换 system prompt
        system = anthropic_request.get("system")
        if system:
            openai_request["messages"].append({
                "role": "system",
                "content": system
            })
        
        # 转换 messages
        messages = anthropic_request.get("messages", [])
        for msg in messages:
            openai_msg = RequestTranslator._convert_message(msg)
            if openai_msg:
                openai_request["messages"].append(openai_msg)
        
        # 转换可选参数
        if "temperature" in anthropic_request:
            openai_request["temperature"] = anthropic_request["temperature"]
        
        if "top_p" in anthropic_request:
            openai_request["top_p"] = anthropic_request["top_p"]
        
        if "stop_sequences" in anthropic_request:
            openai_request["stop"] = anthropic_request["stop_sequences"]
        
        # 转换工具
        tools = anthropic_request.get("tools")
        if tools:
            openai_request["tools"] = RequestTranslator._convert_tools_to_openai(tools)
        
        return openai_request
    
    @staticmethod
    def _convert_message(msg: dict[str, Any]) -> Optional[dict[str, Any]]:
        """转换单条消息"""
        role = msg.get("role")
        content = msg.get("content")
        
        # 处理 content 为列表的情况（多模态）
        if isinstance(content, list):
            # 检查是否包含 tool_use 或 tool_result
            has_tool_use = any(item.get("type") == "tool_use" for item in content)
            has_tool_result = any(item.get("type") == "tool_result" for item in content)
            
            if has_tool_use:
                # assistant 消息包含 tool_calls
                return RequestTranslator._convert_tool_use_message(msg)
            elif has_tool_result:
                # user 消息包含 tool_result
                return RequestTranslator._convert_tool_result_message(msg)
            else:
                # 普通多模态内容
                return {
                    "role": role,
                    "content": RequestTranslator._convert_content(content)
                }
        
        # 简单文本消息
        return {
            "role": role,
            "content": content
        }
    
    @staticmethod
    def _convert_content(content: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """转换内容块"""
        openai_content = []
        
        for item in content:
            item_type = item.get("type")
            
            if item_type == "text":
                openai_content.append({
                    "type": "text",
                    "text": item.get("text", "")
                })
            elif item_type == "image":
                openai_content.append({
                    "type": "image_url",
                    "image_url": {
                        "url": item.get("source", {}).get("data", "")
                    }
                })
        
        return openai_content
    
    @staticmethod
    def _convert_tool_use_message(msg: dict[str, Any]) -> dict[str, Any]:
        """转换包含 tool_use 的消息"""
        content = msg.get("content", [])
        tool_calls = []
        text_content = []
        
        for item in content:
            if item.get("type") == "tool_use":
                tool_calls.append({
                    "id": item.get("id", ""),
                    "type": "function",
                    "function": {
                        "name": item.get("name", ""),
                        "arguments": json.dumps(item.get("input", {}))
                    }
                })
            elif item.get("type") == "text":
                text_content.append(item.get("text", ""))
        
        result = {
            "role": "assistant",
            "content": "\n".join(text_content) if text_content else None
        }
        
        if tool_calls:
            result["tool_calls"] = tool_calls
        
        return result
    
    @staticmethod
    def _convert_tool_result_message(msg: dict[str, Any]) -> list[dict[str, Any]]:
        """转换包含 tool_result 的消息"""
        content = msg.get("content", [])
        messages = []
        
        for item in content:
            if item.get("type") == "tool_result":
                tool_use_id = item.get("tool_use_id", "")
                result_content = item.get("content", "")
                
                # 处理错误情况
                if item.get("is_error"):
                    result_content = f"Error: {result_content}"
                
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_use_id,
                    "content": result_content if isinstance(result_content, str) else json.dumps(result_content)
                })
        
        return messages if len(messages) > 1 else messages[0] if messages else None
    
    @staticmethod
    def _convert_tools_to_openai(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """将 Anthropic 工具格式转换为 OpenAI 格式"""
        openai_tools = []
        
        for tool in tools:
            openai_tools.append({
                "type": "function",
                "function": {
                    "name": tool.get("name", ""),
                    "description": tool.get("description", ""),
                    "parameters": tool.get("input_schema", {})
                }
            })
        
        return openai_tools
    
    @staticmethod
    def openai_to_anthropic(openai_request: dict[str, Any]) -> dict[str, Any]:
        """
        将 OpenAI 请求格式转换为 Anthropic 格式
        """
        anthropic_request = {
            "model": openai_request.get("model", ""),
            "max_tokens": openai_request.get("max_tokens", 1024),
        }
        
        messages = openai_request.get("messages", [])
        
        # 提取 system prompt
        system_messages = [m for m in messages if m.get("role") == "system"]
        if system_messages:
            anthropic_request["system"] = system_messages[0].get("content", "")
            messages = [m for m in messages if m.get("role") != "system"]
        
        # 转换消息
        anthropic_request["messages"] = [
            RequestTranslator._convert_message_to_anthropic(m) for m in messages
        ]
        
        # 转换可选参数
        if "temperature" in openai_request:
            anthropic_request["temperature"] = openai_request["temperature"]
        
        if "top_p" in openai_request:
            anthropic_request["top_p"] = openai_request["top_p"]
        
        if "stop" in openai_request:
            anthropic_request["stop_sequences"] = openai_request["stop"]
        
        # 转换工具
        if "tools" in openai_request:
            anthropic_request["tools"] = RequestTranslator._convert_tools_to_anthropic(
                openai_request["tools"]
            )
        
        return anthropic_request
    
    @staticmethod
    def _convert_message_to_anthropic(msg: dict[str, Any]) -> dict[str, Any]:
        """将 OpenAI 消息转换为 Anthropic 格式"""
        role = msg.get("role")
        content = msg.get("content")
        
        # 处理 tool_calls
        if role == "assistant" and "tool_calls" in msg:
            content_blocks = []
            
            if content:
                content_blocks.append({"type": "text", "text": content})
            
            for tc in msg.get("tool_calls", []):
                content_blocks.append({
                    "type": "tool_use",
                    "id": tc.get("id", ""),
                    "name": tc.get("function", {}).get("name", ""),
                    "input": json.loads(tc.get("function", {}).get("arguments", "{}"))
                })
            
            return {"role": "assistant", "content": content_blocks}
        
        # 处理 tool 响应
        if role == "tool":
            return {
                "role": "user",
                "content": [{
                    "type": "tool_result",
                    "tool_use_id": msg.get("tool_call_id", ""),
                    "content": content
                }]
            }
        
        # 普通消息
        return {"role": role, "content": content}
    
    @staticmethod
    def _convert_tools_to_anthropic(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """将 OpenAI 工具格式转换为 Anthropic 格式"""
        anthropic_tools = []
        
        for tool in tools:
            if tool.get("type") == "function":
                func = tool.get("function", {})
                anthropic_tools.append({
                    "name": func.get("name", ""),
                    "description": func.get("description", ""),
                    "input_schema": func.get("parameters", {})
                })
        
        return anthropic_tools


class ResponseTranslator:
    """响应格式转译器"""
    
    @staticmethod
    def openai_to_anthropic(openai_response: dict[str, Any]) -> dict[str, Any]:
        """
        将 OpenAI 响应格式转换为 Anthropic 格式
        
        OpenAI 格式:
        {
            "id": "chatcmpl-xxx",
            "object": "chat.completion",
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": "Hello"
                    },
                    "finish_reason": "stop"
                }
            ],
            "usage": {
                "prompt_tokens": 10,
                "completion_tokens": 20,
                "total_tokens": 30
            }
        }
        
        Anthropic 格式:
        {
            "id": "msg_xxx",
            "type": "message",
            "role": "assistant",
            "content": [{"type": "text", "text": "Hello"}],
            "model": "claude-3-opus-20240229",
            "stop_reason": "end_turn",
            "usage": {
                "input_tokens": 10,
                "output_tokens": 20
            }
        }
        """
        choice = openai_response.get("choices", [{}])[0]
        message = choice.get("message", {})
        finish_reason = choice.get("finish_reason", "stop")
        
        # 转换内容
        content = []
        
        # 处理 tool_calls
        if "tool_calls" in message:
            for tc in message.get("tool_calls", []):
                content.append({
                    "type": "tool_use",
                    "id": tc.get("id", ""),
                    "name": tc.get("function", {}).get("name", ""),
                    "input": json.loads(tc.get("function", {}).get("arguments", "{}"))
                })
        
        # 处理文本内容
        if message.get("content"):
            content.insert(0, {
                "type": "text",
                "text": message["content"]
            })
        
        # 转换 stop_reason
        stop_reason_map = {
            "stop": "end_turn",
            "length": "max_tokens",
            "tool_calls": "tool_use",
            "content_filter": "end_turn"
        }
        stop_reason = stop_reason_map.get(finish_reason, "end_turn")
        
        # 转换 usage
        usage = openai_response.get("usage", {})
        
        return {
            "id": f"msg_{uuid.uuid4().hex[:24]}",
            "type": "message",
            "role": "assistant",
            "content": content if content else [{"type": "text", "text": ""}],
            "model": openai_response.get("model", ""),
            "stop_reason": stop_reason,
            "usage": {
                "input_tokens": usage.get("prompt_tokens", 0),
                "output_tokens": usage.get("completion_tokens", 0)
            }
        }
    
    @staticmethod
    def anthropic_to_openai(anthropic_response: dict[str, Any]) -> dict[str, Any]:
        """
        将 Anthropic 响应格式转换为 OpenAI 格式
        """
        content = anthropic_response.get("content", [])
        stop_reason = anthropic_response.get("stop_reason", "end_turn")
        
        # 分离文本和工具调用
        text_parts = []
        tool_calls = []
        
        for block in content:
            if block.get("type") == "text":
                text_parts.append(block.get("text", ""))
            elif block.get("type") == "tool_use":
                tool_calls.append({
                    "id": block.get("id", ""),
                    "type": "function",
                    "function": {
                        "name": block.get("name", ""),
                        "arguments": json.dumps(block.get("input", {}))
                    }
                })
        
        # 转换 finish_reason
        finish_reason_map = {
            "end_turn": "stop",
            "max_tokens": "length",
            "tool_use": "tool_calls",
            "stop_sequence": "stop"
        }
        finish_reason = finish_reason_map.get(stop_reason, "stop")
        
        # 构建 message
        message = {
            "role": "assistant",
            "content": "\n".join(text_parts) if text_parts else None
        }
        
        if tool_calls:
            message["tool_calls"] = tool_calls
        
        # 转换 usage
        usage = anthropic_response.get("usage", {})
        
        return {
            "id": f"chatcmpl-{uuid.uuid4().hex[:24]}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": anthropic_response.get("model", ""),
            "choices": [
                {
                    "index": 0,
                    "message": message,
                    "finish_reason": finish_reason
                }
            ],
            "usage": {
                "prompt_tokens": usage.get("input_tokens", 0),
                "completion_tokens": usage.get("output_tokens", 0),
                "total_tokens": usage.get("input_tokens", 0) + usage.get("output_tokens", 0)
            }
        }


# 全局实例
_request_translator: Optional[RequestTranslator] = None
_response_translator: Optional[ResponseTranslator] = None


def get_request_translator() -> RequestTranslator:
    """获取请求转译器实例"""
    global _request_translator
    if _request_translator is None:
        _request_translator = RequestTranslator()
    return _request_translator


def get_response_translator() -> ResponseTranslator:
    """获取响应转译器实例"""
    global _response_translator
    if _response_translator is None:
        _response_translator = ResponseTranslator()
    return _response_translator
