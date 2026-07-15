"""
ContextCompressor - Phase 3: GW-P5 上游前置过滤
递归切片→格式化→LLM压缩→拼接；字符数硬预算。
"""
import logging
from typing import Optional

from ..config import get_section

logger = logging.getLogger(__name__)


class ContextCompressor:
    """上游 System 消息压缩器"""

    def __init__(self):
        config = get_section("upstream_filter")
        self.char_threshold = config.get("char_threshold", 5000)

    def process(self, system_content: str, complexity: str) -> dict:
        """
        根据复杂度处理 system 消息

        Args:
            system_content: 客户端的 system 消息内容
            complexity: chat / prompt_chat / task_chain

        Returns:
            {"action": "drop"|"compress"|"keep", "content": "...", "original_len": N, "compressed_len": N}
        """
        original_len = len(system_content)

        if original_len < self.char_threshold:
            return {"action": "keep", "content": system_content,
                    "original_len": original_len, "compressed_len": original_len}

        if complexity == "chat":
            return self._drop(system_content, original_len)
        elif complexity == "task_chain":
            return self._keep(system_content, original_len)
        else:
            return self._compress(system_content, original_len)

    def _drop(self, content: str, original_len: int) -> dict:
        """简单对话 → 丢弃 system"""
        logger.info(f"Upstream filter: DROP (original={original_len} chars)")
        return {"action": "drop", "content": "", "original_len": original_len, "compressed_len": 0}

    def _keep(self, content: str, original_len: int) -> dict:
        """复杂任务 → 保留 system"""
        logger.info(f"Upstream filter: KEEP (original={original_len} chars)")
        return {"action": "keep", "content": content,
                "original_len": original_len, "compressed_len": original_len}

    def _compress(self, content: str, original_len: int, ratio: float = 0.5) -> dict:
        """专业对话 → 截断压缩"""
        max_len = int(original_len * ratio)
        compressed = content[:max_len] + "\n\n[系统提示已自动压缩]"
        logger.info(f"Upstream filter: COMPRESS (original={original_len} -> {len(compressed)} chars)")
        return {"action": "compress", "content": compressed,
                "original_len": original_len, "compressed_len": len(compressed)}
