"""计划编译器——双输出模式 (v0_1_2 T6)

输入: plan_config.phases[] → 输出: text-cli path JSON
SPEC v1.3.2 §9.2 兼容: steps[].instruction (domain;action格式), output_as, source
方案A: compiler 生成缺省指令（ai;infer），T5 注入管线在运行时补充策略上下文
"""

import logging
from typing import Any

from ..models.pipeline import PlanConfig, PhaseConfig

logger = logging.getLogger(__name__)


class PlanCompiler:
    """计划编译器——PlanConfig → text-cli path JSON"""

    async def compile(self, plan_config: PlanConfig, mode: str = "direct") -> dict:
        """编译 plan_config → SPEC 兼容的 path JSON

        Args:
            plan_config: 计划配置
            mode: "direct" (直通) 或 "edit" (编辑模式——轻量 JSON)

        Returns:
            {"steps": [{"instruction": "ai;infer,...", "output_as": "phase_1", ...}]}
        """
        steps = []
        for pc in plan_config.phases:
            instruction = f"ai;infer,{plan_config.intent or 'execute'},{pc.name},{pc.description}"
            step = {
                "instruction": instruction,
                "output_as": f"phase_{pc.index}",
                "source": pc.source if hasattr(pc, 'source') and pc.source else None,
            }
            # 门控信息嵌入 description（供下游 path 引擎条件执行参考）
            gates_info = (
                f"[GATES] show_terminal={pc.gates.show_terminal}"
                f", allow_path_edit={pc.gates.allow_path_edit}"
                f", require_human_approval={pc.gates.require_human_approval}"
            )
            step["description"] = f"{pc.description}. {gates_info}. mode={pc.mode}"

            # mode_params 仅在 direct 模式下传递
            if mode == "direct" and pc.mode_params:
                step["mode_params"] = pc.mode_params

            steps.append(step)

        # 两种输出模式共享 steps 数组，edit 模式加轻量标记
        result = {"steps": steps, "_schema": "text-cli-path-v1"}
        if mode == "edit":
            result["_mode"] = "edit"

        logger.info(f"Plan compiled: {len(steps)} steps, mode={mode}")
        return result

    async def recompile(self, plan_config: PlanConfig) -> dict:
        """重编译（T9 回退触发时调用）"""
        return await self.compile(plan_config, mode="direct")
