"""
ContextInjector - Phase 4: GW-P3 任务链执行
每步执行前提取已完成步骤的关键数据，注入当前步骤上下文。
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)


class ContextInjector:
    """上下文注入器"""

    def inject(self, current_step: int, step_name: str, completed_steps: list[dict]) -> str:
        """
        为当前步骤构建上下文提示

        Args:
            current_step: 当前步骤序号 (1-based)
            step_name: 当前步骤名称
            completed_steps: 已完成的步骤列表

        Returns:
            上下文提示文本
        """
        parts = []

        if completed_steps:
            parts.append("此前已完成的步骤：")
            for s in completed_steps:
                status = "✅" if s.get("status") == "completed" else "❌"
                parts.append(f"  {status} 步骤{s.get('step_num', '?')}: {s.get('step_name', '')}")
                if s.get("summary"):
                    parts.append(f"     → {s['summary'][:100]}")

        parts.append(f"\n当前执行：步骤{current_step} - {step_name}")

        return "\n".join(parts)
