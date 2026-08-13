"""相位感知注入管线 (v0_1_2 T5)

三步管线：
1. text-cli;query → available_tools
2. strata-match POST /api/v1/query(phase=当前相位) → 策略
3. LLM 注入 context + 策略 → 产出
"""

import json
import logging
from typing import Any, Optional

import httpx

from ..config import load_fractal_prompt
from ..models.pipeline import PipelineSession, PhaseDefinition

logger = logging.getLogger(__name__)


class StrategyUnavailableError(Exception):
    """strata-match 不可达异常"""
    pass


class InjectionPipeline:
    """相位感知注入管线"""

    def __init__(self, textcli_url: str = "http://localhost:28050/text-cli/cli",
                 strata_match_url: str = "http://localhost:13156/api/v1/query"):
        self.textcli_url = textcli_url
        self.strata_match_url = strata_match_url

    # ═══════════════════════════════════════════════════════════
    # 步骤1: text-cli;query → available_tools
    # ═══════════════════════════════════════════════════════════

    async def fetch_available_tools(self) -> list[str]:
        """步骤1: 从 text-cli 获取可用工具列表"""
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    self.textcli_url,
                    json={"prompt": "AI:text-cli;query"},
                )
                resp.raise_for_status()
                data = resp.json()

                # text-cli response wrapper: {rst_types, rst_data: {text: "..."}}
                rst_text = data.get("rst_data", {}).get("text", "")
                if isinstance(rst_text, str):
                    try:
                        inner = json.loads(rst_text)
                        if isinstance(inner, dict) and "directives" in inner:
                            tools = [d.get("usage", f"{d['domain']};{d['action']}")
                                     for d in inner.get("directives", [])]
                        else:
                            tools = []
                    except json.JSONDecodeError:
                        # compact format: one directive per line
                        tools = [line.strip() for line in rst_text.split("\n") if line.strip()]
                else:
                    tools = []
                logger.info(f"Fetched {len(tools)} tools from text-cli")
                return tools
        except Exception as e:
            logger.warning(f"Step 1 failed (text-cli unreachable): {e} — continuing with empty tools")
            return []

    # ═══════════════════════════════════════════════════════════
    # 步骤2: strata-match(含 phase) → 策略
    # ═══════════════════════════════════════════════════════════

    async def fetch_phase_strategy(self, user_ask: str, phase: PhaseDefinition,
                                    available_tools: list[str]) -> dict:
        """步骤2: 从 strata-match 获取相位感知策略"""
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(
                    self.strata_match_url,
                    json={
                        "user_ask": user_ask,
                        "types": "role_play",
                        "phase": {
                            "index": phase.index,
                            "name": phase.name,
                            "description": phase.description,
                            "mode": phase.mode,
                            "gates": phase.gates.to_dict(),
                        },
                        "available_tools": available_tools,
                    },
                )
                resp.raise_for_status()
                data = resp.json()
                logger.info(f"Strategy fetched for phase {phase.index}: {phase.name}")
                return data
        except Exception as e:
            logger.error(f"Step 2 failed (strata-match unreachable): {e}")
            raise StrategyUnavailableError(f"strata-match unreachable: {e}")

    # ═══════════════════════════════════════════════════════════
    # 步骤3: LLM 注入 context + 策略 → 产出
    # ═══════════════════════════════════════════════════════════

    async def inject_and_generate(self, pipeline: PipelineSession,
                                   phase: PhaseDefinition,
                                   strategy: dict,
                                   downstream_llm,
                                   accumulated_context: str = "") -> str:
        """步骤3: 注入上下文 + 策略 → LLM 产出"""
        # 构建系统 prompt
        fractal_prompt = load_fractal_prompt()
        tools_str = ", ".join(
            t.get("usage", t.get("name", ""))
            for t in strategy.get("tools", [])
        )

        system_prompt = f"""{fractal_prompt}

当前相位：{phase.name} - {phase.description}
模式：{phase.mode}
可用工具：{tools_str}
门控：show_terminal={phase.gates.show_terminal}, allow_path_edit={phase.gates.allow_path_edit}, require_human_approval={phase.gates.require_human_approval}
{accumulated_context}

策略指令：
{strategy.get('primary_prompt', '')}"""

        try:
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": pipeline.intent},
            ]
            response = await downstream_llm.chat(messages=messages)
            content = response.get("choices", [{}])[0].get("message", {}).get("content", "")
            logger.info(f"Phase {phase.index} ({phase.name}): LLM generation complete, {len(content)} chars")
            return content
        except Exception as e:
            logger.error(f"Step 3 failed (LLM error): {e}")
            raise

    # ═══════════════════════════════════════════════════════════
    # 完整三步流程
    # ═══════════════════════════════════════════════════════════

    async def execute(self, pipeline: PipelineSession, phase: PhaseDefinition,
                       downstream_llm, user_ask: str = "",
                       accumulated_context: str = "") -> str:
        """执行完整三步注入管线 → 返回相位产出"""
        # 步骤1: 取工具
        tools = await self.fetch_available_tools()

        # 步骤2: 取策略
        strategy = await self.fetch_phase_strategy(
            user_ask=user_ask or pipeline.intent,
            phase=phase,
            available_tools=tools,
        )

        # 步骤3: LLM 注入产出
        output = await self.inject_and_generate(
            pipeline=pipeline,
            phase=phase,
            strategy=strategy,
            downstream_llm=downstream_llm,
            accumulated_context=accumulated_context,
        )

        return output
