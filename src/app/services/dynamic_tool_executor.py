"""动态工具执行器：执行 strata-match 注入的工具（_a P2.3 修订）"""

import json
import logging
from typing import Any, Optional

import httpx

from .textcli_enhanced_client import get_enhanced_client

logger = logging.getLogger(__name__)


class DynamicToolExecutor:
    """动态工具执行器"""

    def __init__(self):
        self.http_client = httpx.AsyncClient(timeout=30)

    async def execute(
        self,
        tool_meta: dict[str, Any],
        arguments: dict[str, Any]
    ) -> dict[str, Any]:
        """
        执行动态工具

        Args:
            tool_meta: 工具的 strata-match 元数据
            arguments: 工具调用参数

        Returns:
            工具执行结果
        """
        subtype = tool_meta.get("subtype")

        if subtype == "textcli":
            return await self._execute_textcli(tool_meta, arguments)
        elif subtype == "mcp":
            return await self._execute_mcp(tool_meta, arguments)
        elif subtype == "api":
            return await self._execute_api(tool_meta, arguments)
        elif subtype == "sdk":
            return await self._execute_sdk(tool_meta, arguments)
        else:
            return {"status": "error", "message": f"Unsupported tool type: {subtype}"}

    async def _execute_textcli(
        self,
        tool_meta: dict[str, Any],
        arguments: dict[str, Any]
    ) -> dict[str, Any]:
        """
        执行 textcli 工具（_a 修订：P2 修复落点）

        - 废除 command.replace 拼装（3.7）——command 降级为 LLM few-shot 参考
        - LLM 指令校验透传（3.4）：LLM 拼 AI: 指令 → sl 校验 startswith("AI:") → 原样透传
        - 走强化客户端（alias 路由 + 令牌注入 + rank 降级）
        """
        # 指令优先：LLM 拼的完整指令（arguments.command / arguments.prompt）
        prompt = arguments.get("command") or arguments.get("prompt") or ""

        if not prompt:
            # 兜底：LLM 未拼完整指令时，用 usage 主干 + 参数替换（不产生双前缀）
            usage = tool_meta.get("usage") or tool_meta.get("command", "")
            for prefix in ("AI:", "指令:"):
                if usage.startswith(prefix):
                    usage = usage[len(prefix):]
                    break
            prompt = usage
            for key, value in arguments.items():
                prompt = prompt.replace(f"{{{key}}}", str(value))

        # 3.4 前缀校验透传：无前缀补 AI:；已带前缀原样透传（不二次拼装，杜绝 AI:AI:）
        if not prompt.startswith("AI:"):
            prompt = f"AI:{prompt}"

        alias = tool_meta.get("endpoint_alias")
        logger.info(f"Executing textcli tool: {prompt} (alias={alias})")

        try:
            client = get_enhanced_client()
            result = await client.call(prompt, alias=alias)

            return {
                "status": "success",
                "rst_types": "text",
                "rst_data": result.data,
                "rst_err": result.rst_err,
            }
        except Exception as e:
            logger.error(f"textcli tool execution failed: {e}")
            return {"status": "error", "message": str(e)}
    
    async def _execute_mcp(
        self,
        tool_meta: dict[str, Any],
        arguments: dict[str, Any]
    ) -> dict[str, Any]:
        """
        执行 MCP 工具
        
        MCP 工具通过 MCP 协议调用
        """
        original = tool_meta.get("original", {})
        name = original.get("name", "")
        
        logger.info(f"Executing MCP tool: {name}, args: {arguments}")
        
        # TODO: 实现 MCP 协议调用
        # 这里需要根据实际的 MCP 服务器地址和协议来实现
        # 暂时返回模拟结果
        return {
            "status": "error",
            "message": "MCP tool execution not yet implemented"
        }
    
    async def _execute_api(
        self,
        tool_meta: dict[str, Any],
        arguments: dict[str, Any]
    ) -> dict[str, Any]:
        """
        执行 API 工具
        
        API 工具通过 HTTP 调用
        """
        endpoint = tool_meta.get("endpoint", "")
        method = tool_meta.get("method", "POST").upper()
        
        logger.info(f"Executing API tool: {method} {endpoint}, args: {arguments}")
        
        if not endpoint:
            return {"status": "error", "message": "API endpoint not configured"}
        
        try:
            if method == "GET":
                response = await self.http_client.get(
                    endpoint,
                    params=arguments
                )
            else:
                response = await self.http_client.post(
                    endpoint,
                    json=arguments
                )
            
            response.raise_for_status()
            
            return {
                "status": "success",
                "data": response.json()
            }
        except httpx.HTTPStatusError as e:
            logger.error(f"API tool execution failed: HTTP {e.response.status_code}")
            return {
                "status": "error",
                "message": f"HTTP {e.response.status_code}: {e.response.text}"
            }
        except Exception as e:
            logger.error(f"API tool execution failed: {e}")
            return {"status": "error", "message": str(e)}
    
    async def _execute_sdk(
        self,
        tool_meta: dict[str, Any],
        arguments: dict[str, Any]
    ) -> dict[str, Any]:
        """
        执行 SDK 工具
        
        SDK 工具需要特殊的执行环境
        """
        sdk_type = tool_meta.get("sdk_type", "")
        
        logger.info(f"Executing SDK tool: {sdk_type}, args: {arguments}")
        
        # TODO: 实现 SDK 调用
        # 这里需要根据 SDK 类型来实现
        # 暂时返回模拟结果
        return {
            "status": "error",
            "message": f"SDK tool execution not yet implemented: {sdk_type}"
        }
    
    async def close(self):
        """关闭客户端"""
        await self.http_client.aclose()


# 全局实例
_executor: Optional[DynamicToolExecutor] = None


def get_dynamic_tool_executor() -> DynamicToolExecutor:
    """获取动态工具执行器实例"""
    global _executor
    if _executor is None:
        _executor = DynamicToolExecutor()
    return _executor
