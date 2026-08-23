"""会话存储（serve/session_store.py）——两层 Session 管理（design §4.5 / dev-plan §3）。

写权归属 serve 层（红线④：core 不持会话写权）。本实现为内存版，
对齐 sl session.py 实测：temp_history = deque(maxlen=20)，永久区
permanent_system_prompt + loaded_docs 独立。

形态①纯 chat：loaded_docs 默认空；两层分离明确，便于闸 get 抽 content 视图。
"""

from __future__ import annotations

from collections import deque
from typing import Any

from ..core.models import SessionView

MAX_TEMP_MESSAGES = 20  # 对齐 sl config.max_temp_messages


class SessionStore:
    """serve 层会话存储：永久区 + 临时滑动窗口。"""

    def __init__(self, max_temp_messages: int = MAX_TEMP_MESSAGES) -> None:
        self.max_temp_messages = max_temp_messages
        self._permanent_system_prompt: str = ""
        self._loaded_docs: list[dict[str, str]] = []
        self._temp_history: deque[dict[str, Any]] = deque(maxlen=max_temp_messages)

    # --- 永久区写（serve 层写权） ---
    def set_permanent_system_prompt(self, prompt: str) -> None:
        self._permanent_system_prompt = prompt

    def add_loaded_doc(self, doc_id: str, content: str) -> None:
        self._loaded_docs.append({"doc_id": doc_id, "content": content})

    # --- 临时区写（serve 层写权，红线⑥之外的正常写点） ---
    def append_turn(self, role: str, content: Any) -> None:
        """追加一轮对话到临时窗口（serve 层唯一会话写点，design §4.5）。"""
        self._temp_history.append({"role": role, "content": content})

    # --- 只读视图（供拼装/闸，红线⑥只读） ---
    def read_view(self) -> SessionView:
        return SessionView(
            permanent_system_prompt=self._permanent_system_prompt,
            loaded_docs=list(self._loaded_docs),
            temp_history=list(self._temp_history),
        )

    @property
    def temp_len(self) -> int:
        return len(self._temp_history)
