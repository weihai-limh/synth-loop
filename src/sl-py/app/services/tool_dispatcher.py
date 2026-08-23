"""工具调度器模块"""

import json
import logging
import time
from typing import Any, Callable, Coroutine, Optional

from ..models.session import Session

logger = logging.getLogger(__name__)


class CircuitBreaker:
    """熔断器"""

    def __init__(
        self,
        failure_threshold: int = 3,
        recovery_timeout: int = 30,
        window_seconds: int = 60,
    ) -> None:
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.window_seconds = window_seconds
        self.failure_times: list[float] = []
        self.is_open_flag = False
        self.open_since: Optional[float] = None

    def record_failure(self) -> None:
        """记录失败"""
        now = time.time()
        # 清理窗口外的失败记录
        self.failure_times = [t for t in self.failure_times if now - t < self.window_seconds]
        self.failure_times.append(now)

        if len(self.failure_times) >= self.failure_threshold:
            self.is_open_flag = True
            self.open_since = now

    def record_success(self) -> None:
        """记录成功"""
        self.failure_times = []
        self.is_open_flag = False
        self.open_since = None

    def is_open(self) -> bool:
        """检查熔断器是否打开"""
        if not self.is_open_flag:
            return False

        # 检查是否已过恢复时间
        if self.open_since and time.time() - self.open_since > self.recovery_timeout:
            self.is_open_flag = False
            self.open_since = None
            self.failure_times = []
            return False

        return True


# 工具处理函数类型
ToolHandler = Callable[[Session, dict[str, Any]], Coroutine[Any, Any, dict[str, Any]]]


class ToolDispatcher:
    """工具调度器"""

    def __init__(
        self,
        failure_threshold: int = 3,
        recovery_timeout: int = 30,
    ) -> None:
        self.registry: dict[str, ToolHandler] = {}
        self.definitions: list[dict[str, Any]] = []
        self.circuit_breakers: dict[str, CircuitBreaker] = {}
        self._failure_threshold = failure_threshold
        self._recovery_timeout = recovery_timeout
        
        # 动态工具支持
        self.dynamic_tools: dict[str, dict[str, Any]] = {}  # 工具元数据
        self.dynamic_definitions: dict[str, dict[str, Any]] = {}  # OpenAI 格式定义

    def register(self, name: str, handler: ToolHandler, definition: dict[str, Any]) -> None:
        """注册内置工具"""
        self.registry[name] = handler
        self.definitions.append(definition)
        self.circuit_breakers[name] = CircuitBreaker(
            failure_threshold=self._failure_threshold,
            recovery_timeout=self._recovery_timeout,
        )

    def register_dynamic_tool(
        self,
        name: str,
        tool_meta: dict[str, Any],
        adapted_definition: dict[str, Any]
    ) -> None:
        """
        注册动态工具（从 strata-match 注入）
        
        Args:
            name: 工具名称
            tool_meta: 工具的 strata-match 元数据
            adapted_definition: 适配后的 OpenAI 工具定义
        """
        self.dynamic_tools[name] = tool_meta
        self.dynamic_definitions[name] = adapted_definition
        self.circuit_breakers[name] = CircuitBreaker(
            failure_threshold=self._failure_threshold,
            recovery_timeout=self._recovery_timeout,
        )
        logger.info(f"注册动态工具: {name}")

    def unregister_dynamic_tool(self, name: str) -> None:
        """注销动态工具"""
        self.dynamic_tools.pop(name, None)
        self.dynamic_definitions.pop(name, None)
        self.circuit_breakers.pop(name, None)
        logger.info(f"注销动态工具: {name}")

    def clear_dynamic_tools(self) -> None:
        """清除所有动态工具"""
        for name in list(self.dynamic_tools.keys()):
            self.unregister_dynamic_tool(name)

    def is_registered(self, tool_name: str) -> bool:
        """检查工具是否在注册表中（包括动态工具）"""
        return tool_name in self.registry or tool_name in self.dynamic_tools

    def is_dynamic_tool(self, tool_name: str) -> bool:
        """检查是否是动态工具"""
        return tool_name in self.dynamic_tools

    def get_dynamic_tool_meta(self, tool_name: str) -> Optional[dict[str, Any]]:
        """获取动态工具的元数据"""
        return self.dynamic_tools.get(tool_name)

    async def execute(self, tool_call: dict[str, Any], session: Session) -> Optional[dict[str, Any]]:
        """
        执行工具调用

        返回:
            工具执行结果，如果是未注册的工具返回 None
        """
        function_info = tool_call.get("function", {})
        name = function_info.get("name", "")

        # 跳过未注册的工具（客户端工具）
        if not self.is_registered(name):
            return None

        # 检查熔断器
        cb = self.circuit_breakers.get(name)
        if cb and cb.is_open():
            return {"error": "工具暂时不可用（熔断中）", "tool_name": name}

        try:
            args = json.loads(function_info.get("arguments", "{}"))
            
            # 检查是否是动态工具
            if self.is_dynamic_tool(name):
                result = await self._execute_dynamic_tool(name, args)
            else:
                handler = self.registry[name]
                result = await handler(session, args)
            
            if cb:
                cb.record_success()
            return result
        except Exception as e:
            if cb:
                cb.record_failure()
            return {"error": str(e), "tool_name": name}

    async def _execute_dynamic_tool(
        self,
        name: str,
        arguments: dict[str, Any]
    ) -> dict[str, Any]:
        """
        执行动态工具
        
        Args:
            name: 工具名称
            arguments: 工具调用参数
        
        Returns:
            工具执行结果
        """
        from .dynamic_tool_executor import get_dynamic_tool_executor
        
        tool_meta = self.get_dynamic_tool_meta(name)
        if not tool_meta:
            return {"error": f"动态工具不存在: {name}"}
        
        executor = get_dynamic_tool_executor()
        return await executor.execute(tool_meta, arguments)

    def get_definitions(self) -> list[dict[str, Any]]:
        """获取所有工具定义（包括动态工具）"""
        all_definitions = list(self.definitions)
        all_definitions.extend(self.dynamic_definitions.values())
        return all_definitions

    def merge_client_tools(
        self, client_tools: Optional[list[dict[str, Any]]]
    ) -> list[dict[str, Any]]:
        """合并内置工具、动态工具和客户端工具定义"""
        tools = list(self.definitions)
        tools.extend(self.dynamic_definitions.values())
        if client_tools:
            tools.extend(client_tools)
        return tools
