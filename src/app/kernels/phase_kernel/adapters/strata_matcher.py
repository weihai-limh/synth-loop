"""strata-match 策略缝（设计稿 §13.6）+ Phase 重构 P3 纠偏（解套 W-8）

Phase 重构 P3（sm 缝）：把"取 strata 策略内容"抽成独立 sm 缝端口 `ports.SmSeam`。
纠偏后（P6 目标态）分层清晰：
- `StrataHttpSm`：sm 缝 HTTP 填缝（实现 `ports.SmSeam`，碰 strata HTTP，phase_path 定位）。
- `StrataMatcher`：**纯 sm 缝填缝**（实现 `ports.SmSeam`），内部组合 `StrataHttpSm` 做两级回退
  （sm 不可用 → None；不再承担 Planner 职责）。
- `PhasePlanPlanner`：**ports.Planner 实现**（消费 sm 内容生成相位树），内部经注入 `sm_seam`
  （默认 StrataMatcher）取策略内容，无 LLM/失败 → MechanicalPlanner 兜底。**pk 消费不获取**（§四-C.3）。

纪律：core/ 零 strata-match / sl import；只有本适配器（adapters/）碰 strata-match HTTP。
--no-strata 时直接走两级回退（默认 prompt + 机械兜底），不发起任何外部请求。
"""

from __future__ import annotations

import asyncio
import json
import urllib.request
from typing import Any, Optional

from ..core.models import PhaseDef, PhasePlan, PhaseGates, SmRequest, SmResponse
from ..ports import SmSeam, Planner
from .mechanical_planner import MechanicalPlanner


class StrataHttpSm:
    """sm 缝 HTTP 填缝：strata-match HTTP 取策略内容（实现 ports.SmSeam）。

    定位用 `SmRequest.phase_path` + name/description（替换旧 phase_meta 手工拼）。
    `--no-strata`/base_url 空 → query 返回 None（走机械兜底）。
    """

    def __init__(self, base_url: Optional[str] = None, no_strata: bool = False):
        self.base_url = base_url
        self.no_strata = no_strata

    async def query(self, req: SmRequest) -> Optional[str]:
        if self.no_strata or not self.base_url:
            return None
        phase_meta = {"name": req.name or req.intent[:80] or "整体规划",
                      "description": req.description or req.name or req.intent or "整体规划"}
        body = json.dumps({"user_ask": req.intent, "phase": phase_meta}).encode("utf-8")
        url = f"{self.base_url.rstrip('/')}/api/v1/query"
        try:
            def _post():
                r = urllib.request.Request(url, data=body, method="POST",
                                           headers={"Content-Type": "application/json"})
                with urllib.request.urlopen(r, timeout=5) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            data = await asyncio.to_thread(_post)
            key = "prompt_cn" if req.lang == "zh" else "prompt"
            return data.get(key) or data.get("primary_prompt")
        except Exception:
            return None


class StrataMatcher:
    """纯 sm 缝填缝（实现 ports.SmSeam，Phase 重构 P3 纠偏：不再承担 Planner 职责）。

    内部组合 `StrataHttpSm` 做两级回退（sm 不可用/失败 → query 返回 None），供上层
    `PhasePlanPlanner` 消费。仅暴露 `query`（SmSeam 契约），无 `plan`/`_resolve_phase`。
    """

    def __init__(self, base_url: Optional[str] = None, no_strata: bool = False,
                 http_sm: Optional[SmSeam] = None):
        self.no_strata = no_strata
        self.http_sm = http_sm or StrataHttpSm(base_url=base_url, no_strata=no_strata)

    async def query(self, req: SmRequest) -> Optional[str]:
        if self.no_strata:
            return None
        return await self.http_sm.query(req)


class PhasePlanPlanner:
    """ports.Planner 实现：消费 sm 内容生成相位树（Phase 重构 P3 纠偏）。

    内部经注入 `sm_seam`（默认 StrataMatcher → StrataHttpSm）取策略内容：
    - 取到 prompt + 有 llm → `_parse_with_llm` 生成相位树（消费完整响应 tools/skills/assets）。
    - 否则 → MechanicalPlanner 兜底（两级回退，P_ctrl 不依赖 LLM 仍可推进）。
    pk 消费不获取（§四-C.3）：planner 只经 sm 缝取内容，不持有 sm 会话。
    """

    def __init__(self, base_url: Optional[str] = None, llm: Optional[Any] = None,
                 no_strata: bool = False, sm_seam: Optional[SmSeam] = None):
        self._llm = llm
        self.no_strata = no_strata
        self.sm_seam = sm_seam or StrataMatcher(base_url=base_url, no_strata=no_strata)
        self._fallback = MechanicalPlanner()

    async def plan(self, goal_repr: Any, context: dict) -> PhasePlan:
        lang = context.get("lang", "zh")
        phase, goal = self._resolve_phase(goal_repr)
        prompt = await self.sm_seam.query(self._make_request(goal, lang, phase))
        if prompt is not None:
            if self._llm is not None:
                try:
                    phases = await self._parse_with_llm(prompt, goal, lang)
                    if phases is not None:
                        return phases
                except Exception:
                    pass
            return await self._fallback.plan(goal, context)
        plan = await self._fallback.plan(goal, context)
        tools = await self._discover_tools(goal, context)
        if tools:
            for p in plan.phases:
                if not p.tools:
                    p.tools = tools
        return plan

    async def regenerate(self, phase, feedback: str) -> PhasePlan:
        return await self._fallback.plan(feedback, {})

    def _make_request(self, goal: str, lang: str,
                      phase: Optional[PhaseDef] = None) -> SmRequest:
        path = phase.path if phase is not None else None
        return SmRequest(phase_path=path, intent=goal, lang=lang,
                         name=phase.name if phase else None,
                         description=phase.description if phase else None)

    def _resolve_phase(self, goal_repr: Any):
        if isinstance(goal_repr, PhaseDef):
            phase = goal_repr
            goal = phase.name or phase.description or ""
            return phase, goal
        return None, str(goal_repr or "")

    async def _discover_tools(self, goal: str, context: dict) -> list:
        tools = context.get("tools")
        if isinstance(tools, list):
            return tools
        return []

    async def _parse_with_llm(self, prompt: str, goal: str, lang: str) -> Optional[PhasePlan]:
        messages = [
            {"role": "system", "content": prompt},
            {"role": "user", "content": f"用户意图：{goal}"},
        ]
        content = await _maybe_await(self._llm(messages))
        data = json.loads(content)
        phases = data.get("phases", [])
        if not phases:
            return None
        return PhasePlan(phases=[
            PhaseDef(index=int(p["index"]), name=p["name"], description=p.get("description", ""),
                     mode=p.get("mode", "single_ai"), gates=PhaseGates.from_dict(p.get("gates", {})),
                     tools=p.get("tools") or [], skills_prompt=p.get("skills_prompt", ""),
                     assets=p.get("assets"))
            for p in phases
        ])


async def _maybe_await(value):
    if hasattr(value, "__await__"):
        return await value
    return value
