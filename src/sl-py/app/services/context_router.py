"""上下文路由器模块"""

from typing import Any, Optional

from ..models.session import Session


def extract_user_content(messages: list[dict[str, Any]]) -> Any:
    """
    提取最后一条 user 消息的 content，保留原始结构
    content 可能是字符串（纯文本）或数组（多模态：图片+文本等）
    """
    for msg in reversed(messages):
        if msg.get("role") == "user":
            return msg.get("content")
    return None


def extract_client_system_messages(messages: list[dict[str, Any]]) -> list[dict[str, str]]:
    """提取客户端传入的 system 消息"""
    return [msg for msg in messages if msg.get("role") == "system"]


class ContextRouter:
    """上下文路由器"""

    def build_messages(
        self,
        session: Session,
        current_user_content: Any = None,
        client_system_messages: Optional[list[dict[str, str]]] = None,
        override_system: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """
        构建最终发送给下游 LLM 的消息数组

        Args:
            session: 会话对象
            current_user_content: 当前用户消息内容（支持多模态）
            client_system_messages: 客户端 system 消息
            override_system: 覆盖 permanent_system_prompt（分形路由等场景）
        """
        messages: list[dict[str, Any]] = []

        # 1. 永久区：Session-ID
        messages.append({"role": "system", "content": f"Session-ID: {session.session_id}"})

        # 2. 永久区：System Prompt（网关管理）；可被 override_system 覆盖
        if override_system is not None:
            messages.append({"role": "system", "content": override_system})
        elif session.permanent_system_prompt:
            messages.append({"role": "system", "content": session.permanent_system_prompt})

        # 3. 永久区：已加载文档
        for doc in session.loaded_docs:
            messages.append({"role": "system", "content": f"=== {doc['doc_id']} ==="})
            messages.append({"role": "system", "content": doc["content"]})

        # 4. 永久区：客户端 system 消息（合并追加，不持久化）
        if client_system_messages:
            messages.extend(client_system_messages)

        # 5. 临时区：滑动窗口历史
        messages.extend(list(session.temp_history))

        # 6. 当前用户消息（保留原始 content 结构，支持多模态）
        if current_user_content is not None:
            messages.append({"role": "user", "content": current_user_content})

        return messages

    def build_prompt_selection_messages(
        self, user_query: str
    ) -> list[dict[str, str]]:
        """构建首轮 Prompt 选择的消息（仅包含用户问题）"""
        return [{"role": "user", "content": user_query}]
