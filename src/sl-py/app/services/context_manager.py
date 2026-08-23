"""
ContextManager - Phase 4: GW-P4 上下文标签管理
manage_context 工具：load/unload/list/refresh 按标签管理永久区上下文。
"""

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

MANAGE_CONTEXT_DEFINITION = {
    "type": "function",
    "function": {
        "name": "manage_context",
        "description": "按标签管理永久区上下文。action: load(加载)/unload(卸载)/list(列出)/refresh(刷新)",
        "parameters": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["load", "unload", "list", "refresh"]},
                "tags": {"type": "array", "items": {"type": "string"}, "description": "标签列表"},
            },
            "required": ["action"],
        },
    },
}


class ContextManager:
    """上下文标签管理器"""

    def __init__(self):
        self._registry: dict[str, dict] = {}  # tag -> {strategy, references}

    def load(self, session, tags: list[str]) -> dict:
        """加载标签到 session 永久区"""
        loaded = []
        for tag in tags:
            if tag not in self._registry:
                self._registry[tag] = {
                    "strategy": f"[{tag}] 相关指导策略",
                    "references": f"[{tag}] 参考资料",
                }
            entry = self._registry[tag]
            # 注入到 session
            current = session.permanent_system_prompt
            if f"[{tag}]" not in current:
                session.permanent_system_prompt = f"{current}\n<strategy>{entry['strategy']}</strategy>"
                loaded.append(tag)
                logger.info(f"ContextManager: loaded tag='{tag}'")

        return {"action": "load", "loaded_tags": loaded}

    def unload(self, session, tags: list[str]) -> dict:
        """卸载标签"""
        removed = []
        for tag in tags:
            current = session.permanent_system_prompt
            if f"[{tag}]" in current:
                import re
                session.permanent_system_prompt = re.sub(
                    f'<strategy>\\[{tag}\\].*?</strategy>', '', current)
                session.permanent_system_prompt = re.sub(
                    f'<references>\\[{tag}\\].*?</references>', '', current)
                removed.append(tag)
                logger.info(f"ContextManager: unloaded tag='{tag}'")

        return {"action": "unload", "removed_tags": removed}

    def list_tags(self, session) -> dict:
        """列出已加载标签"""
        import re
        matches = re.findall(r'\[(.*?)\]', session.permanent_system_prompt)
        tags = list(set(m for m in matches if not m.startswith("<")))
        return {"action": "list", "loaded_tags": tags}


async def handle_manage_context(session, args: dict) -> Any:
    """manage_context 工具处理器
    Args:
        session: 当前会话对象
        args: 工具参数，由 ToolDispatcher.execute() 从 tool_call 中解析传入
    """
    if isinstance(args, str):
        args = json.loads(args)

    action = args.get("action", "list")
    tags = args.get("tags", [])

    mgr = ContextManager()

    if action == "load":
        return mgr.load(session, tags)
    elif action == "unload":
        return mgr.unload(session, tags)
    elif action == "list":
        return mgr.list_tags(session)
    elif action == "refresh":
        mgr.unload(session, tags)
        return mgr.load(session, tags)
    else:
        return {"error": f"Unknown action: {action}"}
