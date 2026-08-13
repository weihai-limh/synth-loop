"""相位 chat 编排器（_a P4.1）——相位 = 多次 chat 的一维契约序列

对外契约（3.6）：
- 响应携带 synth_pipeline: {id, step, phase_index, phase_total, artifact_ref}
- 调用方回传 synth_pipeline: {id, action: confirm|reject|regenerate|regenerate_with_new_context|abort|check_result}
- step 枚举: awaiting_plan_confirm / awaiting_path_confirm / awaiting_approval / executing / completed / aborted

核心职责：
- 相位意图识别（规则优先 + 保守阈值，仅显式表达触发；R6）
- synth_pipeline 回传解析 → 决策点状态机推进
- 两段推理编排：总体规划（planning 场景）→ 逐 phase path（plan_compiler 组装）→ 执行
- P18：无 tc 执行面 → 相位意图降级回任务链
"""

import json
import logging
import re
from typing import Any, Optional
from uuid import uuid4

from ..models.pipeline import (
    PipelineSession, PhaseConfig, PlanConfig, PhaseDefinition, PhaseStatus,
    PipelineStatus, PipelineGates,
)
from .plan_compiler import PlanCompiler
from .phase_executor import PhaseExecutor
from .pipeline_lifecycle import PipelineLifecycleManager
from .textcli_enhanced_client import get_enhanced_client
from .downstream_llm import get_downstream_llm
from .model_selector import ModelSelector

logger = logging.getLogger(__name__)

# 相位意图显式表达词（规则层，R6——规则未命中绝不触发）
_PHASE_INTENT_PATTERNS = [
    r"用相位",
    r"用管道",
    r"pipeline\s*模式",
    r"分阶段(执行|处理|完成)",
    r"相位(模式|驱动)",
]

# 决策点 step 枚举
STEP_AWAITING_PLAN = "awaiting_plan_confirm"
STEP_AWAITING_PATH = "awaiting_path_confirm"
STEP_AWAITING_APPROVAL = "awaiting_approval"
STEP_EXECUTING = "executing"
STEP_COMPLETED = "completed"
STEP_ABORTED = "aborted"

# action 枚举
ACTION_CONFIRM = "confirm"
ACTION_REJECT = "reject"
ACTION_REGENERATE = "regenerate"
ACTION_REGENERATE_NEW_CTX = "regenerate_with_new_context"
ACTION_ABORT = "abort"
ACTION_CHECK_RESULT = "check_result"  # _a R4：长任务结果查询

_PLANNING_SYSTEM_PROMPT = """你是任务规划器。将用户意图拆分为多个相位（phase），每个相位是一个可执行的步骤。

输出格式（严格 JSON）：
{"phases": [{"index": 0, "name": "相位名", "description": "该相位要做什么（含目标）", "mode": "single_ai"}]}

要求：
1. 相位划分要合理，每个相位目标明确
2. 3-6 个相位为佳
3. 只输出 JSON，不要其他文字"""


class PhaseChatOrchestrator:
    """相位 chat 多轮编排器"""

    def __init__(self):
        self.compiler = PlanCompiler()
        self.phase_executor = PhaseExecutor()
        self.lifecycle = PipelineLifecycleManager()
        self._pipelines: dict[str, PipelineSession] = {}

    # ═══════════════════════════════════════════════════════════
    # 相位意图识别（R6：规则优先 + 保守阈值）
    # ═══════════════════════════════════════════════════════════

    def detect_phase_intent(self, user_text: str) -> bool:
        """规则层：显式表达词命中才触发；规则未命中绝不触发（保守，防误触发）"""
        for pattern in _PHASE_INTENT_PATTERNS:
            if re.search(pattern, user_text, re.IGNORECASE):
                return True
        return False

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
        """处理一次带相位语义的 chat 调用，返回响应（content + synth_pipeline 字段）。"""
        # 回传驱动：带 synth_pipeline 字段 → 解析 action
        if synth_pipeline and synth_pipeline.get("id"):
            return await self._handle_action(synth_pipeline, user_text, session_id, user_id)

        # 新发起：相位意图（规则命中才触发）
        if self.detect_phase_intent(user_text):
            return await self._start_planning(user_text, session_id, user_id)

        # 未命中 → 不进入相位（普通请求走原路径）
        raise PhaseNotTriggeredError()

    # ═══════════════════════════════════════════════════════════
    # 新发起：第1段总体规划 → awaiting_plan_confirm
    # ═══════════════════════════════════════════════════════════

    async def _start_planning(self, user_text: str, session_id: Optional[str],
                              user_id: Optional[str]) -> dict:
        pipeline_id = str(uuid4())
        session = PipelineSession(
            intent=user_text,
            plan_config=PlanConfig(phases=[]),
            user_id=user_id,
            pipeline_id=pipeline_id,
            session_id=session_id,
        )
        session.status = PipelineStatus.DRAFT
        self._pipelines[pipeline_id] = session

        # 第1段推理：总体规划（planning 场景）
        plan = await self._generate_overall_plan(user_text)
        phases = [
            PhaseConfig(index=p["index"], name=p["name"], description=p.get("description", ""),
                        mode=p.get("mode", "single_ai"))
            for p in plan
        ]
        session.plan_config = PlanConfig(phases=phases)
        session.phases = [
            PhaseDefinition(index=p.index, name=p.name, description=p.description,
                            mode=p.mode, gates=p.gates)
            for p in phases
        ]

        # 规划内容写入 artifacts（数据面）
        artifact_ref = f"art_{pipeline_id}_plan"
        plan_content = json.dumps([p.to_dict() for p in phases], ensure_ascii=False)

        plan_summary = "；".join(f"{p.name}（{p.description[:30]}）" for p in phases)
        return {
            "content": f"相位规划如下（共 {len(phases)} 个相位）：\n{plan_summary}\n\n"
                       f"请确认（回传 action=confirm）或提出修改意见（action=reject/regenerate）。",
            "synth_pipeline": {
                "id": pipeline_id,
                "step": STEP_AWAITING_PLAN,
                "phase_index": 0,
                "phase_total": len(phases),
                "artifact_ref": artifact_ref,
            },
        }

    async def _generate_overall_plan(self, user_text: str) -> list[dict]:
        """第1段推理：LLM（planning 场景）生成总体规划"""
        from ..config import get_section
        selector = ModelSelector()
        endpoint_name, model = selector.select("planning")
        llm = get_downstream_llm()

        messages = [
            {"role": "system", "content": _PLANNING_SYSTEM_PROMPT},
            {"role": "user", "content": f"用户意图：{user_text}"},
        ]
        try:
            resp = await llm.chat(
                messages=messages,
                model=model or None,
                endpoint_name=endpoint_name,
                max_tokens=1000,
                temperature=0.3,
            )
            content = resp["choices"][0]["message"]["content"]
            data = json.loads(content)
            phases = data.get("phases", [])
            if not phases:
                raise ValueError("规划为空")
            return phases
        except Exception as e:
            logger.warning(f"总体规划 LLM 失败，降级默认规划: {e}")
            return [
                {"index": 0, "name": "需求分析", "description": "分析用户需求"},
                {"index": 1, "name": "执行", "description": "执行主要任务"},
                {"index": 2, "name": "总结", "description": "总结输出结果"},
            ]

    # ═══════════════════════════════════════════════════════════
    # 回传驱动：解析 action → 决策点状态机
    # ═══════════════════════════════════════════════════════════

    async def _handle_action(self, synth_pipeline: dict, user_text: str,
                             session_id: Optional[str], user_id: Optional[str]) -> dict:
        pipeline_id = synth_pipeline.get("id")
        action = synth_pipeline.get("action", "")
        session = self._pipelines.get(pipeline_id)
        if session is None:
            # 会话快照恢复尝试（持久化）
            session = await self._restore_session(pipeline_id, session_id)
            if session is None:
                return {
                    "content": "管道不存在或已过期，请重新发起相位请求。",
                    "synth_pipeline": {"id": pipeline_id, "step": STEP_ABORTED,
                                       "phase_index": 0, "phase_total": 0, "artifact_ref": None},
                }

        if action == ACTION_ABORT:
            session.status = PipelineStatus.ABORTED
            return self._respond(session, STEP_ABORTED, "管道已中止。")

        if action == ACTION_REJECT:
            # 意见走 content（字段只带动作）
            feedback = user_text or "no feedback"
            current = session.get_current_phase()
            if current and current.status == PhaseStatus.AWAITING_APPROVAL:
                await self.phase_executor.reject_phase(session, current.index, feedback)
                return self._respond(session, STEP_AWAITING_APPROVAL,
                                     f"已驳回，反馈：{feedback[:100]}。请确认是否重新执行（confirm）或中止（abort）。")
            return self._respond(session, STEP_AWAITING_PLAN, f"已驳回规划，反馈：{feedback[:100]}。")

        if action == ACTION_REGENERATE or action == ACTION_REGENERATE_NEW_CTX:
            # 重新生成（不改变/基于新上下文）
            return await self._regenerate(session, user_text)

        if action == ACTION_CHECK_RESULT:
            # R4 长任务结果查询
            return await self._check_result(session)

        if action == ACTION_CONFIRM:
            return await self._confirm(session)

        # 未知 action → 409 语义
        return {
            "content": f"未知 action: {action}",
            "synth_pipeline": {"id": pipeline_id, "step": session.status.value,
                               "phase_index": 0, "phase_total": len(session.phases), "artifact_ref": None},
        }

    async def _confirm(self, session: PipelineSession) -> dict:
        """confirm：按当前 step 推进"""
        current = session.get_current_phase()

        # awaiting_plan_confirm → 启动管道，生成第一个相位 path
        if session.status == PipelineStatus.DRAFT or (current is None and session.phases):
            await self.lifecycle.start(session)
            return await self._generate_next_path(session, 0)

        # awaiting_path_confirm → 提交执行
        if current and current.status == PhaseStatus.AWAITING_PATH_CONFIRM:
            return await self._execute_phase(session, current)

        # awaiting_approval → 审批通过
        if current and current.status == PhaseStatus.AWAITING_APPROVAL:
            await self.phase_executor.approve_phase(session, current.index)
            # 推进到下一相位
            next_index = current.index + 1
            if next_index < len(session.phases):
                return await self._generate_next_path(session, next_index)
            session.status = PipelineStatus.COMPLETED
            return self._respond(session, STEP_COMPLETED, "所有相位已完成！")

        return self._respond(session, STEP_AWAITING_PLAN, "当前状态无法 confirm。")

    # ═══════════════════════════════════════════════════════════
    # 第2段推理：生成 phase path（plan_compiler 组装）
    # ═══════════════════════════════════════════════════════════

    async def _generate_next_path(self, session: PipelineSession, phase_index: int) -> dict:
        phase = session.phases[phase_index]
        phase.status = PhaseStatus.AWAITING_PATH_CONFIRM

        # 组装 path（LLM 产物 → tc path 信封；plan_compiler 校验/填充）
        path = await self.compiler.assemble(
            {"steps": [], "id": f"{session.pipeline_id}_p{phase_index}", "name": phase.name},
            phase,
        )

        artifact_ref = f"art_{session.pipeline_id}_path_{phase_index}"
        path_display = json.dumps(path, ensure_ascii=False)[:500]
        return {
            "content": f"相位 {phase_index + 1}/{len(session.phases)}「{phase.name}」的 path 如下：\n"
                       f"{path_display}\n\n确认执行（confirm）/ 驳回修改（reject + 意见）/ 中止（abort）。",
            "synth_pipeline": {
                "id": session.pipeline_id,
                "step": STEP_AWAITING_PATH,
                "phase_index": phase_index,
                "phase_total": len(session.phases),
                "artifact_ref": artifact_ref,
            },
        }

    # ═══════════════════════════════════════════════════════════
    # 执行（经强化客户端委托 tc；长任务分级 R4）
    # ═══════════════════════════════════════════════════════════

    async def _execute_phase(self, session: PipelineSession, phase: PhaseDefinition) -> dict:
        phase.status = PhaseStatus.RUNNING
        client = get_enhanced_client()
        prompt = f"AI:text-cli;path,{json.dumps({'steps': []}, ensure_ascii=False)}"
        # 简化执行：委托 tc（mock 环境返回 pending/ok）
        try:
            result = await client.call(prompt, alias=phase.endpoint_alias)
            if result.is_async:
                # 长任务：返回 task_id → check_result 决策点（R4）
                phase.status = PhaseStatus.RUNNING
                return {
                    "content": f"相位「{phase.name}」已提交异步执行，task_id={result.task_id}。"
                               f"查询结果请回传 action=check_result。",
                    "synth_pipeline": {
                        "id": session.pipeline_id,
                        "step": STEP_EXECUTING,
                        "phase_index": phase.index,
                        "phase_total": len(session.phases),
                        "artifact_ref": f"art_{session.pipeline_id}_result_{phase.index}",
                    },
                }
            # 同步完成
            await self.phase_executor.confirm_path(session, phase.index, confirmed=True)
            phase.status = PhaseStatus.COMPLETED
            summary = json.dumps(result.data, ensure_ascii=False)[:200]
            session.phase_summaries.append(summary)

            next_index = phase.index + 1
            if next_index < len(session.phases):
                return await self._generate_next_path(session, next_index)
            session.status = PipelineStatus.COMPLETED
            return self._respond(session, STEP_COMPLETED, "所有相位已完成！")
        except Exception as e:
            logger.error(f"相位执行失败: {e}")
            phase.status = PhaseStatus.FAILED
            return self._respond(session, STEP_ABORTED, f"相位执行失败：{e}")

    async def _check_result(self, session: PipelineSession) -> dict:
        """R4：长任务结果查询（check_result 决策点）"""
        current = session.get_current_phase()
        # 简化的结果查询：返回当前状态
        return self._respond(session, STEP_EXECUTING, "任务仍在执行中（mock 环境）。")

    async def _regenerate(self, session: PipelineSession, feedback: str) -> dict:
        """重新生成（feedback 为修正意见）"""
        current = session.get_current_phase()
        if current is None:
            return await self._start_planning(session.intent, session.session_id, session.user_id)
        # 重新生成当前相位 path
        current.status = PhaseStatus.AWAITING_PATH_CONFIRM
        return await self._generate_next_path(session, current.index)

    # ═══════════════════════════════════════════════════════════
    # 响应构造 + 持久化
    # ═══════════════════════════════════════════════════════════

    def _respond(self, session: PipelineSession, step: str, content: str) -> dict:
        current = session.get_current_phase()
        return {
            "content": content,
            "synth_pipeline": {
                "id": session.pipeline_id,
                "step": step,
                "phase_index": current.index if current else 0,
                "phase_total": len(session.phases),
                "artifact_ref": None,
            },
        }

    async def _restore_session(self, pipeline_id: str, session_id: Optional[str]) -> Optional[PipelineSession]:
        """会话快照恢复（跨 chat 轮次）——简化为按 session_id 从内存/快照恢复"""
        # v0.1.2 内存态；会话快照持久化见 pipeline-session_zh.md（Phase 后续）
        return None


class PhaseNotTriggeredError(Exception):
    """相位未触发（普通请求，走原路径）"""


# 全局实例
_orchestrator: Optional[PhaseChatOrchestrator] = None


def get_phase_orchestrator() -> PhaseChatOrchestrator:
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = PhaseChatOrchestrator()
    return _orchestrator
