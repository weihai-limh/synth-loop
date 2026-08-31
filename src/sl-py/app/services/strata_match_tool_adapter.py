"""strata-match 工具适配器：将 strata-match 工具转换为 OpenAI 格式"""

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


class StrataMatchToolAdapter:
    """将 strata-match 返回的工具转换为 OpenAI 工具格式"""
    
    def adapt(self, tool: dict[str, Any]) -> Optional[dict[str, Any]]:
        """
        适配工具
        
        Args:
            tool: strata-match 返回的工具（ToolCompactResponse 格式）
        
        Returns:
            OpenAI 工具格式，不支持的类型返回 None
        """
        subtype = tool.get("subtype")
        
        if subtype == "textcli":
            return self._adapt_textcli(tool)
        elif subtype == "mcp":
            return self._adapt_mcp(tool)
        elif subtype == "api":
            return self._adapt_api(tool)
        elif subtype == "sdk":
            return self._adapt_sdk(tool)
        else:
            logger.warning(f"Unsupported tool type: {subtype}")
            return None
    
    def _adapt_textcli(self, tool: dict[str, Any]) -> dict[str, Any]:
        """
        适配 textcli 工具
        
        textcli 工具通过 call_textcli 元工具执行，这里生成一个包装工具
        """
        name = tool.get("name", "")
        description = tool.get("description", "")
        command = tool.get("command", "")
        params = tool.get("params", [])
        
        # 构建参数 schema
        properties = {}
        required = []
        
        if params:
            for param in params:
                properties[param] = {
                    "type": "string",
                    "description": f"参数 {param}"
                }
                required.append(param)
        else:
            # 如果没有参数，使用 command 作为默认参数
            properties["command"] = {
                "type": "string",
                "description": "text-cli 命令",
                "default": command
            }
        
        return {
            "type": "function",
            "function": {
                "name": name,
                "description": description,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required if required else ["command"]
                }
            },
            "_strata_match_meta": {
                "subtype": "textcli",
                "command": command,
                "endpoint_alias": tool.get("endpoint_alias"),   # _a P3: 逻辑端点名（可选）
                "estimated_time": tool.get("estimated_time"),   # _a P5: 耗时预估（可选）
                "usage": tool.get("usage"),                     # domain;action（LLM 参考拼 AI: 指令）
                "original": tool
            }
        }
    
    def _adapt_mcp(self, tool: dict[str, Any]) -> dict[str, Any]:
        """
        适配 MCP 工具
        
        MCP 工具使用完整的 JSON Schema 定义
        """
        name = tool.get("name", "")
        description = tool.get("description", "")
        definition = tool.get("definition", {})
        
        # 提取 parameters
        parameters = definition.get("parameters", {})
        if not parameters:
            parameters = {"type": "object", "properties": {}}
        
        return {
            "type": "function",
            "function": {
                "name": name,
                "description": description,
                "parameters": parameters
            },
            "_strata_match_meta": {
                "subtype": "mcp",
                "definition": definition,
                "original": tool
            }
        }
    
    def _adapt_api(self, tool: dict[str, Any]) -> dict[str, Any]:
        """
        适配 API 工具
        
        API 工具使用 HTTP 调用
        """
        name = tool.get("name", "")
        description = tool.get("description", "")
        definition = tool.get("definition", {})
        
        # 提取 parameters
        parameters = definition.get("parameters", {})
        if not parameters:
            parameters = {"type": "object", "properties": {}}
        
        return {
            "type": "function",
            "function": {
                "name": name,
                "description": description,
                "parameters": parameters
            },
            "_strata_match_meta": {
                "subtype": "api",
                "endpoint": definition.get("endpoint", ""),
                "method": definition.get("method", "POST"),
                "original": tool
            }
        }
    
    def _adapt_sdk(self, tool: dict[str, Any]) -> dict[str, Any]:
        """
        适配 SDK 工具
        
        SDK 工具需要特殊的执行环境
        """
        name = tool.get("name", "")
        description = tool.get("description", "")
        definition = tool.get("definition", {})
        
        # 提取 parameters
        parameters = definition.get("parameters", {})
        if not parameters:
            parameters = {"type": "object", "properties": {}}
        
        return {
            "type": "function",
            "function": {
                "name": name,
                "description": description,
                "parameters": parameters
            },
            "_strata_match_meta": {
                "subtype": "sdk",
                "sdk_type": definition.get("sdk_type", ""),
                "original": tool
            }
        }
    
    def extract_meta(self, adapted_tool: dict[str, Any]) -> dict[str, Any]:
        """提取工具的 strata-match 元数据"""
        return adapted_tool.get("_strata_match_meta", {})


# 全局实例
_adapter: Optional[StrataMatchToolAdapter] = None


def get_tool_adapter() -> StrataMatchToolAdapter:
    """获取工具适配器实例"""
    global _adapter
    if _adapter is None:
        _adapter = StrataMatchToolAdapter()
    return _adapter
