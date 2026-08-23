"""上下文累积策略 (v0_1_2 T4)

每相位产出 LLM 摘要 (≤200 字)，注入 = 前序摘要 + 当前策略
"""

import logging
from ..models.pipeline import PipelineSession

logger = logging.getLogger(__name__)


def build_context(pipeline: PipelineSession, current_phase_index: int,
                   current_strategy: str = "") -> str:
    """构建当前相位的注入上下文

    注入 = 前序相位累积摘要 + 当前策略提示
    """
    parts = []

    # 前序累积上下文
    if pipeline.accumulated_context:
        parts.append(f"[前序相位累积]\n{pipeline.accumulated_context}")

    # 当前策略
    if current_strategy:
        parts.append(f"[当前策略]\n{current_strategy}")

    return "\n\n".join(parts) if parts else ""


def accumulate_summary(pipeline: PipelineSession, phase_index: int,
                        summary: str, max_chars: int = 200) -> str:
    """累积相位摘要到 pipeline（截断至 max_chars）"""
    truncated = summary[:max_chars]
    prefix = f"[Phase {phase_index + 1}] " if pipeline.accumulated_context else f"[Phase {phase_index + 1}] "
    pipeline.accumulated_context += prefix + truncated + "\n"
    logger.debug(f"Phase {phase_index + 1} summary accumulated ({len(truncated)} chars)")
    return truncated
