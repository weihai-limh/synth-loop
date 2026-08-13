"""Phase 1: 可靠性底座测试 (v0_1_2)"""

import pytest
from app.services.task_chain_executor import TaskChainExecutor, StepExecutionError, TaskCancelledError


class TestStepExecutionError:
    """步骤执行异常正确传播"""

    def test_contains_step_name_and_original_error(self):
        """StepExecutionError 包含 step_name 和 original_error"""
        original = ValueError("LLM connection timeout")
        error = StepExecutionError(step_name="需求分析", original_error=original)

        assert error.step_name == "需求分析"
        assert error.original_error is original
        assert "需求分析" in str(error)
        assert "LLM connection timeout" in str(error)

    def test_inherits_from_exception(self):
        """StepExecutionError 继承自 Exception"""
        error = StepExecutionError(step_name="test", original_error=RuntimeError("boom"))
        assert isinstance(error, Exception)

    def test_can_be_caught_separately(self):
        """StepExecutionError 可独立捕获（不会被通用 Exception 误捕后才识别）"""
        with pytest.raises(StepExecutionError):
            raise StepExecutionError(step_name="compile", original_error=ConnectionError("refused"))


class TestTaskCancelledError:
    """TaskCancelledError 回归验证"""

    def test_contains_chain_id(self):
        error = TaskCancelledError(chain_id="sg-test-123")
        assert error.chain_id == "sg-test-123"
        assert "sg-test-123" in str(error)
