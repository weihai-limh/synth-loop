"""相位感知注入管线（_a P4 收敛）——复用基础组件

旧实现（v0.1.2）：三步管线各自自建 httpx + 自建 system prompt——sm 缓存/降级失效（P10）、
请求级上下文丢失（P11）、无熔断（P12）。
新实现（_a）：三步管线全部收敛为基础组件——相位旅程与旅程 A 共用同一套实现
（P10 收敛边界：相位留"大脑"不留"手脚"）。
"""

import json
import logging
from typing import Any, Optional

from ..models.pipeline import PipelineSession, PhaseDefinition
from .textcli_enhanced_client import get_enhanced_client
from .strata_match_client import get_strata_match_client
from .context_router import ContextRouter

logger = logging.getLogger(__name__)


class StrategyUnavailableError(Exception):
    """strata-match 不可达异常"""
    pass


class InjectionPipeline:
    """相位感知注入管线（收敛为基础组件）"""

    def __init__(self):
        self.client = get_enhanced_client()          # 收敛：强化客户端（P10）
        self.sm_client = get_strata_match_client()   # 收敛：sm 客户端（缓存/降级，P10）
        self.context_router = ContextRouter()        # 收敛：请求级上下文（P11）

    # ═══════════════════════════════════════════════════════════
    # 步骤1: 取工具 —— 经强化客户端 discover
    # ═══════════════════════════════════════════════════════════

    async def fetch_available_tools(self) -> list[str]:
        """步骤1: 经强化客户端 discover（对齐 tc call.py），不再自建 httpx"""
        try:
            directives = await self.client.discover("json")
            tools = [
                d.get("usage", f"{d['domain']};{d['action']}")
                for d in directives
            ]
            logger.info(f"Fetched {len(tools)} tools from text-cli")
            return tools
        except Exception as e:
            logger.warning(f"Step 1 failed (text-cli unreachable): {e} — continuing with empty tools")
            return []

    # ═══════════════════════════════════════════════════════════
    # 步骤2: 取策略 —— 经 strata_match_client（缓存 TTL + mock + 降级）
    # ═══════════════════════════════════════════════════════════

    async def fetch_phase_strategy(self, user_ask: str, phase: PhaseDefinition,
                                    available_tools: list[str]) -> dict:
        """步骤2: 经 sm 客户端（复用缓存/mock/降级），不再自建 httpx"""
        try:
            return await self.sm_client.query(
                user_ask=user_ask,
                types="role_play",
                phase={
                    "index": phase.index,
                    "name": phase.name,
                    "description": phase.description,
                    "mode": phase.mode,
                    "gates": phase.gates.to_dict(),
                },
                available_tools=available_tools,
            )
        except Exception as e:
            logger.error(f"Step 2 failed (strata-match unreachable): {e}")
            raise StrategyUnavailableError(f"strata-match unreachable: {e}")

    # ═══════════════════════════════════════════════════════════
    # 步骤3: LLM 注入 —— 复用 context_router 组装（P11 修复）
    # ═══════════════════════════════════════════════════════════

    async def inject_and_generate(self, pipeline: PipelineSession,
                                   phase: PhaseDefinition,
                                   strategy: dict,
                                   downstream_llm,
                                   accumulated_context: str = "",
                                   session: Any = None) -> str:
        """步骤3: context_router 六层组装 + 叠加相位专属段（P11：请求级上下文可见）

        Args:
            session: 真实 Session（chat 旅程上下文）——有则复用请求级上下文（P11 修复）；
                     无则退化为纯相位 prompt（不崩，兼容无 session 场景）
        """
        tools_str = ", ".join(
            t.get("usage", t.get("name", ""))
            for t in strategy.get("tools", [])
        )
        # 相位专属段（叠加在基础之上，不替代）
        phase_system = (
            f"当前相位：{phase.name} - {phase.description}\n"
            f"模式：{phase.mode}\n"
            f"可用工具：{tools_str}\n"
            f"门控：show_terminal={phase.gates.show_terminal}, "
            f"allow_path_edit={phase.gates.allow_path_edit}, "
            f"require_human_approval={phase.gates.require_human_approval}\n"
            f"{accumulated_context}\n\n"
            f"策略指令：\n{strategy.get('primary_prompt', '')}"
        )

        if session is not None:
            # P11 修复：复用 context_router（Session-ID/System Prompt/文档/历史/当前消息可见）
            base_messages = self.context_router.build_messages(
                session=session, current_user_content=pipeline.intent,
            )
            messages = [{"role": "system", "content": phase_system}] + base_messages
        else:
            messages = [
                {"role": "system", "content": phase_system},
                {"role": "user", "content": pipeline.intent},
            ]

        try:
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
        # 步骤1: 取工具（失败降级 []）
        tools = await self.fetch_available_tools()

        # 步骤2: 取策略（sm 不可达 → StrategyUnavailableError → 相位 failed）
        strategy = await self.fetch_phase_strategy(
            user_ask=user_ask or pipeline.intent,
            phase=phase,
            available_tools=tools,
        )

        # 步骤3: LLM 注入产出（异常上抛，不吞）
        output = await self.inject_and_generate(
            pipeline=pipeline,
            phase=phase,
            strategy=strategy,
            downstream_llm=downstream_llm,
            accumulated_context=accumulated_context,
        )
        return output
