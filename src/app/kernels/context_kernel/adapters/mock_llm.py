"""Mock LLM 提供方（adapters/mock_llm.py）——测试/验证用（dev-plan 各 Phase 门禁）。

closed 模式端到端验证使用；P4 开闸流程也用 mock（不调真实 LLM）。
返回结构对齐 sl llm_provider.chat 的 usage / content 形态摘要。
"""

from __future__ import annotations

from typing import Any

from ..ports import LlmProvider


class MockLlmProvider(LlmProvider):
    def __init__(self, reply_content: str = "<mock reply>") -> None:
        self.reply_content = reply_content
        self.last_call: dict[str, Any] | None = None

    def chat(
        self,
        messages: list[dict[str, Any]],
        model: str,
        stream: bool = False,
        service_name: Any = None,
    ) -> Any:
        self.last_call = {
            "messages": messages,
            "model": model,
            "stream": stream,
            "service_name": service_name,
        }
        return {
            "choices": [
                {"message": {"role": "assistant", "content": self.reply_content}}
            ],
            "model": model,
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        }
