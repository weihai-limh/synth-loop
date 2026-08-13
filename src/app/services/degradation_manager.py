"""降级管理器：实现三级降级机制"""

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


class DegradationLevel:
    """降级级别"""
    FULL = "full"           # 完整模式：strata-match 可用
    DEGRADED = "degraded"   # 降级模式：使用兜底 Prompt + 内置工具
    FAILURE = "failure"     # 故障模式：返回错误


class DegradationManager:
    """降级管理器"""
    
    def __init__(self):
        self._failure_count = 0
        self._failure_threshold = 3
        self._recovery_timeout = 60  # 秒
        self._last_failure_time = 0
    
    async def execute_with_degradation(
        self,
        full_mode_func,
        degraded_mode_func,
        failure_mode_func,
        *args,
        **kwargs
    ) -> tuple[Any, str]:
        """
        执行降级逻辑
        
        Args:
            full_mode_func: 完整模式执行函数
            degraded_mode_func: 降级模式执行函数
            failure_mode_func: 故障模式执行函数
            *args, **kwargs: 传递给函数的参数
        
        Returns:
            (result, degradation_level)
        """
        # 检查是否处于故障模式
        if self._is_in_failure_mode():
            logger.warning("Currently in failure mode, falling back to degraded mode")
            try:
                result = await degraded_mode_func(*args, **kwargs)
                return result, DegradationLevel.DEGRADED
            except Exception as e:
                logger.error(f"Degraded mode also failed: {e}")
                result = await failure_mode_func(*args, **kwargs)
                return result, DegradationLevel.FAILURE
        
        # 尝试完整模式
        try:
            result = await full_mode_func(*args, **kwargs)
            self._record_success()
            return result, DegradationLevel.FULL
        except Exception as e:
            logger.warning(f"Full mode failed: {e}")
            self._record_failure()
            
            # 尝试降级模式
            try:
                result = await degraded_mode_func(*args, **kwargs)
                return result, DegradationLevel.DEGRADED
            except Exception as e2:
                logger.error(f"Degraded mode also failed: {e2}")
                result = await failure_mode_func(*args, **kwargs)
                return result, DegradationLevel.FAILURE
    
    def _is_in_failure_mode(self) -> bool:
        """检查是否处于故障模式"""
        if self._failure_count >= self._failure_threshold:
            # 检查是否超过恢复时间
            import time
            current_time = time.time()
            if current_time - self._last_failure_time > self._recovery_timeout:
                # 重置计数器，允许重试
                self._failure_count = 0
                return False
            return True
        return False
    
    def _record_failure(self) -> None:
        """记录失败"""
        import time
        self._failure_count += 1
        self._last_failure_time = time.time()
        logger.warning(f"Recorded failure, current failure count: {self._failure_count}")
    
    def _record_success(self) -> None:
        """记录成功"""
        self._failure_count = 0
        logger.info("Recorded success, reset failure counter")
    
    def reset(self) -> None:
        """重置状态"""
        self._failure_count = 0
        self._last_failure_time = 0


class SmartPromptDegradation:
    """strata-match 降级处理器"""
    
    def __init__(self):
        self._degradation_manager = DegradationManager()
    
    async def get_strategy(
        self,
        strata_match_client,
        user_query: str,
        default_prompt: str
    ) -> tuple[str, str, dict[str, Any]]:
        """
        获取策略，支持降级
        
        Args:
            strata_match_client: strata-match 客户端
            user_query: 用户查询
            default_prompt: 默认 Prompt
        
        Returns:
            (prompt_text, degradation_level, strata_match_result)
        """
        # 完整模式：调用 strata-match
        async def full_mode():
            result = await strata_match_client.query(user_query)
            if not result or not result.get("primary_prompt"):
                raise ValueError("strata-match returned empty result")
            return result
        
        # 降级模式：使用默认 Prompt
        async def degraded_mode():
            return {
                "primary_prompt": default_prompt,
                "tools": [],
                "assets": [],
                "degradation_reason": "strata-match unavailable"
            }
        
        # 故障模式：返回错误
        async def failure_mode():
            return {
                "primary_prompt": default_prompt,
                "tools": [],
                "assets": [],
                "degradation_reason": "system failure",
                "error": True
            }
        
        result, level = await self._degradation_manager.execute_with_degradation(
            full_mode,
            degraded_mode,
            failure_mode
        )
        
        prompt_text = result.get("primary_prompt", default_prompt)
        
        logger.info(f"Strategy acquisition complete, degradation level: {level}")
        
        return prompt_text, level, result


# 全局实例
_degradation: Optional[SmartPromptDegradation] = None


def get_degradation_manager() -> SmartPromptDegradation:
    """获取降级管理器实例"""
    global _degradation
    if _degradation is None:
        _degradation = SmartPromptDegradation()
    return _degradation
