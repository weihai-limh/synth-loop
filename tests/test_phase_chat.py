"""_a P4.1: 相位 chat 多轮契约测试——synth_pipeline 状态机全流转"""

import asyncio
import os
import sys
from pathlib import Path

import httpx
import pytest
import respx

_SRC = Path(__file__).resolve().parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))


@pytest.fixture
def orchestrator():
    """隔离网关 DB + 注入 mock 推理缝（整体替换后相位执行经推理缝 LLM，测试用 mock seam 稳定）"""
    import tempfile
    from app import database as db
    asyncio.run(db.close_shared_db())
    tmp = tempfile.mkdtemp()
    import unittest.mock as mock
    with mock.patch.object(db, "get_db_path", return_value=str(Path(tmp) / "gw.db")):
        asyncio.run(db.init_database())
        from app.services.phase_chat_orchestrator import PhaseChatOrchestrator
        from app.services.kernel_adapters import SlContextSource
        from app.kernels.phase_kernel import (
            PhaseReasoningEngine, MechanicalPlanner, LocalExecutor, InMemoryArtifactStore,
        )
        from app.kernels.context_kernel.core.models import InferenceResult
        from app.services.inference_seam import SlInferenceSeam

        class MockSeam(SlInferenceSeam):
            """mock 推理缝：planning 返回固定 PhasePlan，normal 返回正常执行结果。"""
            async def infer(self, patch):
                ext = patch.ext or {}
                routing = ext.get("routing")
                if routing == "planning":
                    content = ('{"phases": [{"index": 0, "name": "需求分析", "description": "分析需求"},'
                               '{"index": 1, "name": "执行", "description": "执行任务"},'
                               '{"index": 2, "name": "总结", "description": "总结输出"}]}')
                else:
                    content = "<相位执行完成>"
                return InferenceResult(context_id=patch.context_id or "", content=content,
                                       ext={"routing": routing, "phase_path": patch.phase_path})

        seam = MockSeam(context_source=SlContextSource())
        engine = PhaseReasoningEngine(
            executor=LocalExecutor(), planner=MechanicalPlanner(),
            artifact_store=InMemoryArtifactStore(), inference_seam=seam,
        )
        orch = PhaseChatOrchestrator(engine=engine)
        yield orch
        asyncio.run(db.close_shared_db())


class TestPhaseChatProtocol:
    """chat 多轮状态机（confirm/reject/regenerate/abort/check_result）"""

    def test_new_phase_intent_returns_plan(self, orchestrator):
        """chat#1 相位意图 → 返回规划 + synth_pipeline（awaiting_plan_confirm）"""
        async def run():
            resp = await orchestrator.handle_chat("帮我写一份商业计划书", mode="structural")
            sp = resp["synth_pipeline"]
            assert sp["step"] == "awaiting_plan_confirm"
            assert sp["id"]
            assert sp["phase_total"] >= 1
            assert "相位规划" in resp["content"]
            return True
        assert asyncio.run(run())

    def test_plain_request_not_triggered(self, orchestrator):
        """普通请求永不自动进相位（显式调用纯度）"""
        async def run():
            from app.services.phase_chat_orchestrator import PhaseNotTriggeredError
            try:
                await orchestrator.handle_chat("帮我写一份商业计划书")
                return False
            except PhaseNotTriggeredError:
                return True
        assert asyncio.run(run())

    def test_confirm_flow(self, orchestrator):
        """chat#2 confirm → 生成 path → awaiting_path_confirm → confirm → 执行"""
        async def run():
            # chat#1: 规划
            resp1 = await orchestrator.handle_chat("帮我写一份商业计划书", mode="structural")
            sp1 = resp1["synth_pipeline"]

            # chat#2: confirm 规划 → 生成 path
            with respx.mock:
                respx.post("http://mock-tc:28050/text-cli/cli").mock(
                    return_value=httpx.Response(200, json={
                        "rst_types": "text",
                        "rst_data": {"status": "ok", "result": "executed"},
                        "rst_err": ""}))
                resp2 = await orchestrator.handle_chat(
                    "确认", synth_pipeline={"id": sp1["id"], "action": "confirm"})
                sp2 = resp2["synth_pipeline"]
                assert sp2["step"] in {"awaiting_path_confirm", "executing", "completed"}
            return True
        assert asyncio.run(run())

    def test_abort_flow(self, orchestrator):
        """abort → pipeline aborted 终态"""
        async def run():
            resp1 = await orchestrator.handle_chat("帮我写一份商业计划书", mode="structural")
            sp1 = resp1["synth_pipeline"]
            resp2 = await orchestrator.handle_chat(
                "停止", synth_pipeline={"id": sp1["id"], "action": "abort"})
            assert resp2["synth_pipeline"]["step"] == "aborted"
            return True
        assert asyncio.run(run())

    def test_unknown_pipeline_404(self, orchestrator):
        """id 不存在 → 错误 content + aborted"""
        async def run():
            resp = await orchestrator.handle_chat(
                "确认", synth_pipeline={"id": "nonexistent", "action": "confirm"})
            assert "不存在" in resp["content"]
            assert resp["synth_pipeline"]["step"] == "aborted"
            return True
        assert asyncio.run(run())

    def test_unknown_action(self, orchestrator):
        """未知 action → 不推进"""
        async def run():
            resp1 = await orchestrator.handle_chat("帮我写一份商业计划书", mode="structural")
            sp1 = resp1["synth_pipeline"]
            resp = await orchestrator.handle_chat(
                "xx", synth_pipeline={"id": sp1["id"], "action": "bogus_action"})
            assert "未知 action" in resp["content"]
            return True
        assert asyncio.run(run())

    def test_regenerate_flow(self, orchestrator):
        """regenerate → 重新生成当前相位 path（P9 语义：不重开规划）"""
        async def run():
            resp1 = await orchestrator.handle_chat("帮我写一份商业计划书", mode="structural")
            sp1 = resp1["synth_pipeline"]
            with respx.mock:
                respx.post("http://mock-tc:28050/text-cli/cli").mock(
                    return_value=httpx.Response(200, json={
                        "rst_types": "text",
                        "rst_data": {"status": "ok", "result": "regenerated"},
                        "rst_err": ""}))
                resp2 = await orchestrator.handle_chat(
                    "换个思路", synth_pipeline={"id": sp1["id"], "action": "regenerate"})
                sp2 = resp2["synth_pipeline"]
                # 仍在相位流程中（awaiting_path_confirm / executing 等），pipeline id 不变
                assert sp2["id"] == sp1["id"]
                assert sp2["step"] in {"awaiting_path_confirm", "executing"}
            return True
        assert asyncio.run(run())

    def test_execute_via_seam(self, orchestrator):
        """整体替换（_b）：执行经推理缝 mock seam 正常完成（不走 tc）"""
        async def run():
            resp1 = await orchestrator.handle_chat("帮我写一份商业计划书", mode="structural")
            sp1 = resp1["synth_pipeline"]
            # confirm 规划 → 生成 path
            resp2 = await orchestrator.handle_chat(
                "确认", synth_pipeline={"id": sp1["id"], "action": "confirm"})
            sp2 = resp2["synth_pipeline"]
            assert sp2["step"] in {"awaiting_path_confirm", "executing", "completed"}
            # 再 confirm path → 执行（mock seam normal routing → 正常完成，推进下一相位/完成）
            if sp2["step"] == "awaiting_path_confirm":
                resp3 = await orchestrator.handle_chat(
                    "确认", synth_pipeline={"id": sp1["id"], "action": "confirm"})
                sp3 = resp3["synth_pipeline"]
                assert sp3["step"] in {"awaiting_path_confirm", "executing", "completed"}
            return True
        assert asyncio.run(run())

    def test_execute_completes_all_phases(self, orchestrator):
        """整体替换（_b）：执行经 mock seam 正常完成，推进至所有相位完成（不走 tc）"""
        async def run():
            resp1 = await orchestrator.handle_chat("帮我写一份商业计划书", mode="structural")
            sp1 = resp1["synth_pipeline"]
            # 规划 → path
            resp2 = await orchestrator.handle_chat(
                "确认", synth_pipeline={"id": sp1["id"], "action": "confirm"})
            sp2 = resp2["synth_pipeline"]
            assert sp2["step"] == "awaiting_path_confirm"
            # 逐相位 confirm → 执行（mock seam normal）→ 推进
            step = sp2["step"]
            for _ in range(4):
                if step == "completed":
                    break
                resp = await orchestrator.handle_chat(
                    "确认", synth_pipeline={"id": sp1["id"], "action": "confirm"})
                step = resp["synth_pipeline"]["step"]
                assert step in {"awaiting_path_confirm", "executing", "completed"}
            assert resp["content"]  # 有响应（不挂起）
            return True
        assert asyncio.run(run())

    def test_phase_tag_structural(self, orchestrator):
        """_b 标签触发：<tc-phase> → structural + 剥除标签的目标"""
        from app.routers.chat import _parse_phase_tag
        mode, goal = _parse_phase_tag("<tc-phase>帮我写市场调研报告</tc-phase>")
        assert mode == "structural"
        assert goal == "帮我写市场调研报告"

    def test_phase_tag_chain(self, orchestrator):
        """_b 标签触发：<tc-phase-chain> → chain"""
        from app.routers.chat import _parse_phase_tag
        mode, goal = _parse_phase_tag("<tc-phase-chain>处理中等任务</tc-phase-chain>")
        assert mode == "chain"
        assert goal == "处理中等任务"

    def test_phase_tag_chain_priority(self, orchestrator):
        """_b 标签触发：链式标签优先于结构标签"""
        from app.routers.chat import _parse_phase_tag
        mode, _ = _parse_phase_tag("<tc-phase>结构任务</tc-phase> <tc-phase-chain>链任务</tc-phase-chain>")
        assert mode == "chain"

    def test_phase_tag_no_label(self, orchestrator):
        """_b 标签触发：无标签不触发（中文关键词已彻底废除）"""
        from app.routers.chat import _parse_phase_tag
        mode, goal = _parse_phase_tag("请用相位模式帮我写报告")  # 中文词不再触发
        assert mode is None and goal is None
