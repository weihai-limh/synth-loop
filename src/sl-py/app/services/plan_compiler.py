"""计划组装器（Plan Compiler，_a P4 重写）——LLM 产物 → tc path 信封

旧角色（v0.1.2）：编译器——plan_config → 生成 ai;infer 占位指令的 path JSON（P9 双 LLM 分裂）。
新角色（_a）：组装/校验器——sl LLM 第2段推理直接产出 phase path（具体工具指令 step，
无 ai;infer），本组件负责：
1. 校验：path JSON 结构对齐 tc A4 path-engine schema（_schema: text-cli-path-v1）
2. 组装：门控信息嵌入 description；output_as/source/default_source 规范化
3. 路由填充：凭 endpoint_alias 查运行时表得 url → 填入 source/default_source（3.8 P4）
"""

import json
import logging
from typing import Any, Optional

from ..models.pipeline import PhaseConfig, PhaseDefinition, PlanConfig

logger = logging.getLogger(__name__)


class PlanCompiler:
    """计划组装器——LLM path 产物 → 校验/组装 → tc path 信封"""

    async def assemble(
        self,
        path_candidate: dict,
        phase: Any,
        alias_resolver: Optional[callable] = None,
    ) -> dict:
        """组装/校验 LLM 产出的 path。

        Args:
            path_candidate: LLM 产出的 path（可能只有 id/name/steps 占位）
            phase: PhaseDefinition（门控/描述来源）
            alias_resolver: alias → url 解析器（缺省用运行时表）

        Returns:
            正式 tc path 信封（_schema: text-cli-path-v1）
        """
        # 1. 校验：结构对齐 A4
        steps = path_candidate.get("steps", [])
        if not isinstance(steps, list):
            raise ValueError("path steps 必须为数组")

        # 2. 组装：门控嵌入 description + 规范化
        gates = phase.gates.to_dict() if hasattr(phase, "gates") and phase.gates else {}
        description = path_candidate.get("description") or getattr(phase, "description", "")
        gates_info = (
            f"[GATES] show_terminal={gates.get('show_terminal', True)}"
            f", allow_path_edit={gates.get('allow_path_edit', False)}"
            f", require_human_approval={gates.get('require_human_approval', False)}"
        )
        if gates_info not in description:
            description = f"{description}. {gates_info}"

        path = {
            "id": path_candidate.get("id", f"path_{phase.index if hasattr(phase, 'index') else 'x'}"),
            "name": path_candidate.get("name", getattr(phase, "name", "")),
            "type": "pipeline",
            "version": "0.1.0",
            "mode": path_candidate.get("mode", "toolchain"),
            "description": description,
            "requires": path_candidate.get("requires", []),
            "steps": steps,
            "_schema": "text-cli-path-v1",
        }

        # 3. 路由填充：alias → url（default_source / step.source）
        alias = getattr(phase, "endpoint_alias", None)
        if alias:
            url = await self._resolve_alias_url(alias, alias_resolver)
            if url:
                path["default_source"] = url
                for step in steps:
                    if isinstance(step, dict) and not step.get("source"):
                        step["source"] = url

        return path

    async def _resolve_alias_url(self, alias: str, resolver: Optional[callable] = None) -> Optional[str]:
        """alias → url（经运行时表）"""
        try:
            if resolver:
                return await resolver(alias)
            from .runtime_endpoints import resolve_alias
            rows = await resolve_alias(alias)
            return rows[0]["url"] if rows else None
        except Exception as e:
            logger.warning(f"alias resolution failed: {alias} - {e}")
            return None

    # 兼容旧接口（Phase 4 前的 4 个 TestPlanCompiler 测试已按新语义重写）
    async def compile(self, plan_config: PlanConfig, mode: str = "direct") -> dict:
        """（保留旧签名兼容——新语义返回 steps 组装结果）

        按 _a 语义：plan_config.phases → steps[]（具体指令由第2段 LLM 产出；
        此处为结构占位，无 ai;infer）。
        """
        steps = []
        for pc in plan_config.phases:
            instruction = f"{pc.description or 'execute'}"  # 无 ai;infer（P9 修复）
            step = {
                "id": f"phase_{pc.index}",
                "instruction": instruction,
                "output_as": f"phase_{pc.index}",
            }
            if mode == "direct" and getattr(pc, "mode_params", None):
                step["mode_params"] = pc.mode_params
            steps.append(step)

        result = {"steps": steps, "_schema": "text-cli-path-v1"}
        if mode == "edit":
            result["_mode"] = "edit"
        return result

    async def recompile(self, plan_config: PlanConfig) -> dict:
        """重编译（T9 回退触发时调用）"""
        return await self.compile(plan_config, mode="direct")
