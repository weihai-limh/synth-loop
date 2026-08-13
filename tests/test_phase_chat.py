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
    """隔离网关 DB + mock LLM（规划降级默认 + 执行 mock tc）"""
    import tempfile
    from app import database as db
    from app.config import get_config
    asyncio.run(db.close_shared_db())
    tmp = tempfile.mkdtemp()
    import unittest.mock as mock
    with mock.patch.object(db, "get_db_path", return_value=str(Path(tmp) / "gw.db")):
        asyncio.run(db.init_database())
        # 运行时表：mock tc 端点
        from app.services.runtime_endpoints import create_endpoint
        asyncio.run(create_endpoint({
            "alias": "home-service", "url": "http://mock-tc:28050/text-cli/cli",
            "auth": "none", "rank": 1,
        }))
        from app.services.phase_chat_orchestrator import PhaseChatOrchestrator
        # 加载 execution_router（model_config.yaml）——planning/summarize 场景路由
        from app.services.execution_router import get_execution_router
        from app.services.downstream_llm import get_downstream_llm
        router = get_execution_router(str(_SRC / "model_config.yaml"))
        get_downstream_llm().set_execution_router(router)
        orch = PhaseChatOrchestrator()
        yield orch
        asyncio.run(db.close_shared_db())


class TestPhaseChatProtocol:
    """chat 多轮状态机（confirm/reject/regenerate/abort/check_result）"""

    def test_new_phase_intent_returns_plan(self, orchestrator):
        """chat#1 相位意图 → 返回规划 + synth_pipeline（awaiting_plan_confirm）"""
        async def run():
            resp = await orchestrator.handle_chat("请用相位模式帮我写一份商业计划书")
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
            resp1 = await orchestrator.handle_chat("请用相位模式帮我写一份商业计划书")
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
            resp1 = await orchestrator.handle_chat("请用相位模式帮我写一份商业计划书")
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
            resp1 = await orchestrator.handle_chat("请用相位模式帮我写一份商业计划书")
            sp1 = resp1["synth_pipeline"]
            resp = await orchestrator.handle_chat(
                "xx", synth_pipeline={"id": sp1["id"], "action": "bogus_action"})
            assert "未知 action" in resp["content"]
            return True
        assert asyncio.run(run())

    def test_regenerate_flow(self, orchestrator):
        """regenerate → 重新生成当前相位 path（P9 语义：不重开规划）"""
        async def run():
            resp1 = await orchestrator.handle_chat("请用相位模式帮我写一份商业计划书")
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

    def test_check_result_long_task(self, orchestrator):
        """R4 长任务：tc 返回 pending + task_id → check_result 决策点轮询"""
        async def run():
            resp1 = await orchestrator.handle_chat("请用相位模式帮我写一份商业计划书")
            sp1 = resp1["synth_pipeline"]
            # 第一次 confirm：确认规划 → 生成 path → awaiting_path_confirm
            resp2 = await orchestrator.handle_chat(
                "确认", synth_pipeline={"id": sp1["id"], "action": "confirm"})
            sp2 = resp2["synth_pipeline"]
            assert sp2["step"] == "awaiting_path_confirm"
            # 第二次 confirm：确认 path → 执行 → tc 返回异步 pending（长任务）
            with respx.mock:
                respx.post("http://mock-tc:28050/text-cli/cli").mock(
                    return_value=httpx.Response(200, json={
                        "rst_types": "text",
                        "rst_data": {"status": "pending", "task_id": "task-001"},
                        "rst_err": ""}))
                resp3 = await orchestrator.handle_chat(
                    "确认", synth_pipeline={"id": sp1["id"], "action": "confirm"})
                sp3 = resp3["synth_pipeline"]
                assert sp3["step"] == "executing"
                assert "check_result" in resp3["content"]
            # 轮询：check_result 决策点
            resp4 = await orchestrator.handle_chat(
                "查询结果", synth_pipeline={"id": sp1["id"], "action": "check_result"})
            assert resp4["synth_pipeline"]["step"] == "executing"
            return True
        assert asyncio.run(run())

    def test_tc_unreachable_phase_degraded(self, orchestrator):
        """P18：相位执行 tc 不可达 → 降级响应（不崩、不挂起）"""
        async def run():
            resp1 = await orchestrator.handle_chat("请用相位模式帮我写一份商业计划书")
            sp1 = resp1["synth_pipeline"]
            # 第一次 confirm：规划 → path
            resp2 = await orchestrator.handle_chat(
                "确认", synth_pipeline={"id": sp1["id"], "action": "confirm"})
            sp2 = resp2["synth_pipeline"]
            assert sp2["step"] == "awaiting_path_confirm"
            # 第二次 confirm：执行——tc 不 mock（连接失败）→ 相位降级
            resp3 = await orchestrator.handle_chat(
                "确认", synth_pipeline={"id": sp1["id"], "action": "confirm"})
            sp3 = resp3["synth_pipeline"]
            assert sp3["step"] in {"aborted", "executing"}
            assert resp3["content"]  # 有降级消息（不挂起）
            return True
        assert asyncio.run(run())
