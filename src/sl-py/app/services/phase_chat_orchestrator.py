"""相位 chat 编排器（_a P4.1 → _b P5.3 整体替换为 pk 引擎 → 标签触发）

对外契约（3.6，不变）：
- 响应携带 synth_pipeline: {id, step, phase_index, phase_total, artifact_ref}
- 调用方回传 synth_pipeline: {id, action: confirm|reject|regenerate|regenerate_with_new_context|abort|check_result}
- step 枚举: awaiting_plan_confirm / awaiting_path_confirm / awaiting_approval / executing / completed / aborted

_b P5.3 整体替换：相位状态机归 pk `PhaseReasoningEngine`（经 build_phase_engine 装配
四缝 + SlInferenceSeam 推理缝）。本类为薄壳委托。

触发（_b 标签机制，取代中文关键词）：
- 相位由 chat.py 前置解析 XML 标签 `<tc-phase>`（structural）/ `<tc-phase-chain>`（chain）触发
- 本类 `handle_chat` 接收 `mode`（structural/chain），直接传给 pk；不再自行判定相位意图
- 中文关键词触发（用相位/用链）已彻底废除
"""

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

# 相位模式常量（与 pk handle() 白名单一致）
_PHASE_MODE_STRUCTURAL = "structural"
_PHASE_MODE_CHAIN = "chain"


class PhaseChatOrchestrator:
    """相位 chat 多轮编排器（_b P5.3：整体替换为 pk 引擎，薄壳委托；标签触发）"""

    def __init__(self, engine: Optional[Any] = None):
        from .kernel_adapters import build_phase_engine, SlContextSource
        # 装配 pk 引擎（四缝 + SlInferenceSeam 推理缝；_e Phase 3.2 接 sm）
        self._context_source = SlContextSource()
        # _e Phase 3.2：从 sl config.yaml 取 strata_match url 传入 build_phase_engine（接 sm）
        strata_url = None
        try:
            from ..config import get_section
            strata_url = get_section("strata_match").get("url")
        except Exception:
            strata_url = None  # 配置缺失 → 不接 sm（PhasePlanPlanner.no_strata=True 回落机械兜底）
        self._engine = engine or build_phase_engine(
            context_source=self._context_source, strata_base_url=strata_url)

    async def handle_chat(
        self,
        user_text: str,
        synth_pipeline: Optional[dict] = None,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        mode: Optional[str] = None,
    ) -> dict:
        """处理一次带相位语义的 chat 调用，返回响应（content + synth_pipeline 字段）。

        _b：委托 pk `PhaseReasoningEngine.handle()`。
        - 回传驱动（带 synth_pipeline.id）→ 传 synth_pipeline 给 pk _handle_action
        - 新发起 → mode 由 chat.py 标签解析传入（structural/chain）→ 传 pk handle()
        - mode 为 None 且无 synth_pipeline → 未触发相位（抛 PhaseNotTriggeredError）

        _e（i18n）：sl 单语，`lang="zh"` 硬编码（显式，防未来 pk 默认变动）；不改 handle 公开 API。
        """
        if synth_pipeline and synth_pipeline.get("id"):
            return await self._engine.handle(
                user_text, synth_pipeline=synth_pipeline,
                session_id=session_id, user_id=user_id, lang="zh",
            )

        # 新发起：mode 由 chat.py 前置标签解析传入（<tc-phase>/<tc-phase-chain>）
        if mode is not None:
            return await self._engine.handle(
                user_text, synth_pipeline=None,
                session_id=session_id, user_id=user_id, mode=mode, lang="zh",
            )

        # 无 mode 且无 synth_pipeline → 不进入相位（普通请求走原路径）
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
