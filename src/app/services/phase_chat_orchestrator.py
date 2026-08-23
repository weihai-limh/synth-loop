"""相位 chat 编排器（_a P4.1 → _b P5.3 整体替换为 pk 引擎）

对外契约（3.6，不变）：
- 响应携带 synth_pipeline: {id, step, phase_index, phase_total, artifact_ref}
- 调用方回传 synth_pipeline: {id, action: confirm|reject|regenerate|regenerate_with_new_context|abort|check_result}
- step 枚举: awaiting_plan_confirm / awaiting_path_confirm / awaiting_approval / executing / completed / aborted

_b P5.3 整体替换：相位状态机归 pk `PhaseReasoningEngine`（经 build_phase_engine 装配
四缝 + SlInferenceSeam 推理缝）。本类为薄壳委托（handle_chat 签名兼容，chat.py 路由层不改）。
sl 不再自持 PhaseExecutor / PipelineLifecycleManager / PlanCompiler 状态机（退役）。

核心职责（保留）：
- 相位意图识别（规则优先 + 保守阈值，仅显式表达触发；R6，P1 返回模式档 structural/chain）
- synth_pipeline 回传 → 委托 pk handle() 推进状态机
"""

import logging
import re
from typing import Any, Optional

logger = logging.getLogger(__name__)

# 相位意图显式表达词（规则层，R6——规则未命中绝不触发）
# P1（_b）：拆成两组——结构分形（structural，复杂任务）∥ 链式分形（chain，中等任务）。
# detect_phase_intent 返回模式档（structural/chain/None），而非 bool。
_PHASE_MODE_STRUCTURAL = "structural"
_PHASE_MODE_CHAIN = "chain"

# 结构分形显式词：相位按结构层层展开（复杂任务）
_PHASE_INTENT_PATTERNS = [
    r"用相位",
    r"用管道",
    r"pipeline\s*模式",
    r"分阶段(执行|处理|完成)",
    r"相位(模式|驱动)",
]

# 链式分形显式词：相位根分形、子相位直接 LEAF 出 path（中等任务）
_PHASE_CHAIN_PATTERNS = [
    r"用链",
    r"链式(相位|模式|处理)",
    r"chain\s*(模式|处理)",
    r"中等复杂度(相位|管道)?",
]


class PhaseChatOrchestrator:
    """相位 chat 多轮编排器（_b P5.3：整体替换为 pk 引擎，薄壳委托）

    对外契约不变（handle_chat 签名兼容，chat.py 路由层不改）。
    内部实现（整体替换）：相位状态机归 pk `PhaseReasoningEngine`（经 build_phase_engine
    装配四缝 + SlInferenceSeam 推理缝）。sl 不再自持 PhaseExecutor / PipelineLifecycleManager
    / PlanCompiler 状态机（退役）。detect_phase_intent 保留（P1 模式档判定）。
    """

    def __init__(self, engine: Optional[Any] = None):
        from .kernel_adapters import build_phase_engine, SlContextSource
        # 装配 pk 引擎（四缝 + SlInferenceSeam 推理缝）
        self._context_source = SlContextSource()
        self._engine = engine or build_phase_engine(context_source=self._context_source)

    # ═══════════════════════════════════════════════════════════
    # 相位意图识别（R6：规则优先 + 保守阈值）
    # ═══════════════════════════════════════════════════════════

    def detect_phase_intent(self, user_text: str) -> Optional[str]:
        """规则层：返回相位模式档（P1，_b）。

        返回 `structural`（结构分形，复杂任务）/ `chain`（链分形，中等任务）/ `None`（不触发）。
        规则未命中绝不触发（保守，防误触发，R6）。链式词优先于结构词判定（更具体）。
        """
        # 链式显式词优先（更具体，代表用户指定链式模式）
        for pattern in _PHASE_CHAIN_PATTERNS:
            if re.search(pattern, user_text, re.IGNORECASE):
                return _PHASE_MODE_CHAIN
        for pattern in _PHASE_INTENT_PATTERNS:
            if re.search(pattern, user_text, re.IGNORECASE):
                return _PHASE_MODE_STRUCTURAL
        return None

    # ═══════════════════════════════════════════════════════════
    # 主入口：处理一次 chat（相位模式）
    # ═══════════════════════════════════════════════════════════

    async def handle_chat(
        self,
        user_text: str,
        synth_pipeline: Optional[dict] = None,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> dict:
        """处理一次带相位语义的 chat 调用，返回响应（content + synth_pipeline 字段）。

        _b P5.3：委托 pk `PhaseReasoningEngine.handle()`（整体替换状态机）。
        - 回传驱动（带 synth_pipeline.id）→ 传 synth_pipeline 给 pk _handle_action
        - 新发起 → detect_phase_intent 拿 mode（structural/chain）→ 传 pk handle()
        """
        if synth_pipeline and synth_pipeline.get("id"):
            return await self._engine.handle(
                user_text, synth_pipeline=synth_pipeline,
                session_id=session_id, user_id=user_id,
            )

        # 新发起：相位意图（规则命中才触发，P1 返回模式档 structural/chain）
        mode = self.detect_phase_intent(user_text)
        if mode is not None:
            return await self._engine.handle(
                user_text, synth_pipeline=None,
                session_id=session_id, user_id=user_id, mode=mode,
            )

        # 未命中 → 不进入相位（普通请求走原路径）
        raise PhaseNotTriggeredError()


class PhaseNotTriggeredError(Exception):
    """相位未触发（普通请求，走原路径）"""


# 全局实例
_orchestrator: Optional[PhaseChatOrchestrator] = None


def get_phase_orchestrator() -> PhaseChatOrchestrator:
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = PhaseChatOrchestrator()
    return _orchestrator
