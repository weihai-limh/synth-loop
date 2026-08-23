"""
SystemPromptBuilder - v0_1_1: gateway-context XML + 语言保持 prompt
构建 <gateway-context> XML 三段式结构：strategy / references / tools_meta
"""
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

# v0_1_1 Phase 5: 语言保持 prompt
LANGUAGE_KEEP_PROMPT = "Always use the same language as the user's latest message unless user explicitly asks."


class SystemPromptBuilder:
    """Gateway Context XML 构建器"""

    def build(
        self,
        strategy: str = "",
        references: Optional[list[str]] = None,
        skills_tags: Optional[list[str]] = None,
        tools_meta: Optional[list[str]] = None,
    ) -> str:
        """
        构建 gateway-context XML（v0_1_1: 顶层加入语言保持 prompt）

        Args:
            strategy: 策略/角色 Prompt（来自 strata-match）
            references: 参考资料段
            skills_tags: 匹配到的 skills 标签
            tools_meta: 可用工具元信息

        Returns:
            XML 格式的 gateway-context 字符串
        """
        parts = []

        # v0_1_1: 语言保持 prompt — 最顶层
        parts.append(f"<system>{LANGUAGE_KEEP_PROMPT}</system>")

        # <strategy> 段 - 核心策略
        if strategy:
            parts.append(f"<strategy>\n{strategy}\n</strategy>")

        # <references> 段 - 参考资料/上下文
        refs = references or []
        if skills_tags:
            refs.append(f"Related skills: {', '.join(skills_tags)}")
        if refs:
            parts.append(f"<references>\n" + "\n".join(refs) + "\n</references>")

        # <tools_meta> 段 - 可用工具
        if tools_meta:
            parts.append(f"<tools_meta>\n" + "\n".join(tools_meta) + "\n</tools_meta>")

        if not parts:
            return ""

        return "\n".join(parts)
