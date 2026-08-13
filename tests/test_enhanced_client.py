"""_a P2.2: 强化客户端测试——SPEC 1.3.2 信封直读 / 前缀透传 / rank 降级 / 鉴权不降级"""

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
def gw_db(tmp_path, monkeypatch):
    """隔离 gateway.db"""
    from app import database as db
    asyncio.run(db.close_shared_db())
    monkeypatch.setattr(db, "get_db_path", lambda: str(tmp_path / "test_gateway.db"))
    os.environ["SELF_TOKEN_ENC_KEY"] = "test-enc-key-for-client"
    yield db
    asyncio.run(db.close_shared_db())


@pytest.fixture
def seeded_endpoints(gw_db):
    """种子：msllm 两物理行（rank1/rank2）+ home-service（default）"""
    from app.services.runtime_endpoints import create_endpoint

    async def run():
        await gw_db.init_database()
        await create_endpoint({"alias": "msllm", "url": "http://mock-tc1:28050/text-cli/cli",
                               "auth": "none", "rank": 1})
        await create_endpoint({"alias": "msllm", "url": "http://mock-tc2:28050/text-cli/cli",
                               "auth": "none", "rank": 2})
        await create_endpoint({"alias": "home-service", "url": "http://mock-home:28050/text-cli/cli",
                               "auth": "none", "rank": 10})
    asyncio.run(run())
    return gw_db


class TestParseEnvelope:
    """SPEC 1.3.2 信封解析（P15）"""

    def test_sync_direct(self):
        from app.services.textcli_enhanced_client import parse_envelope
        r = parse_envelope({"rst_types": "text", "rst_data": {"status": "ok", "result": 4}, "rst_err": ""})
        assert r.ok
        assert r.data == {"status": "ok", "result": 4}
        assert not r.is_async

    def test_async_pending_task_id(self):
        from app.services.textcli_enhanced_client import parse_envelope
        r = parse_envelope({"rst_types": "text",
                            "rst_data": {"status": "pending", "task_id": "tc-001"},
                            "rst_err": ""})
        assert r.is_async
        assert r.task_id == "tc-001"

    def test_error_closed_set(self):
        from app.services.textcli_enhanced_client import parse_envelope
        r = parse_envelope({"rst_types": "text",
                            "rst_data": {"status": "error", "reason": "nf"},
                            "rst_err": "ERR_NOT_FOUND"})
        assert not r.ok
        assert r.rst_err == "ERR_NOT_FOUND"

    def test_old_nested_text_fallback(self):
        """兼容旧嵌套兜底（不依赖）"""
        from app.services.textcli_enhanced_client import parse_envelope
        r = parse_envelope({"rst_types": "text",
                            "rst_data": '{"status": "ok", "result": 9}',
                            "rst_err": ""})
        assert r.ok
        assert r.data.get("result") == 9


class TestEnhancedClient:
    """强化客户端执行面"""

    def test_call_prefix_passthrough(self, seeded_endpoints):
        """前缀校验透传：AI: 原样，无前缀自动补（不产生 AI:AI:）"""
        from app.services.textcli_enhanced_client import EnhancedTextCliClient

        async def run():
            client = EnhancedTextCliClient()
            with respx.mock:
                respx.post("http://mock-tc1:28050/text-cli/cli").mock(
                    return_value=httpx.Response(200, json={
                        "rst_types": "text", "rst_data": {"status": "ok", "result": 14}, "rst_err": ""}))
                r = await client.call("AI:tc-math;eval,2+2", alias="msllm")
                sent = respx.calls.last.request.content.decode()
                assert "AI:AI:" not in sent
                assert r.ok and r.data["result"] == 14
            return True
        assert asyncio.run(run())

    def test_rank_degradation(self, seeded_endpoints):
        """同 alias rank 降级：rank1 失败 → rank2"""
        from app.services.textcli_enhanced_client import EnhancedTextCliClient

        async def run():
            client = EnhancedTextCliClient()
            with respx.mock:
                respx.post("http://mock-tc1:28050/text-cli/cli").mock(
                    return_value=httpx.Response(500, json={"rst_err": "ERR_ROUTING"}))
                respx.post("http://mock-tc2:28050/text-cli/cli").mock(
                    return_value=httpx.Response(200, json={
                        "rst_types": "text", "rst_data": {"status": "ok", "result": 99}, "rst_err": ""}))
                r = await client.call("AI:tc-math;eval,2+2", alias="msllm")
                assert r.ok and r.data["result"] == 99
            return True
        assert asyncio.run(run())

    def test_auth_failure_no_degradation(self, seeded_endpoints):
        """鉴权败（ACCESS_DENIED）不降级——不尝试 rank2"""
        from app.services.textcli_enhanced_client import EnhancedTextCliClient

        async def run():
            client = EnhancedTextCliClient()
            with respx.mock:
                respx.post("http://mock-tc1:28050/text-cli/cli").mock(
                    return_value=httpx.Response(200, json={
                        "rst_types": "text",
                        "rst_data": {"status": "error", "reason": "denied"},
                        "rst_err": "ACCESS_DENIED"}))
                respx.post("http://mock-tc2:28050/text-cli/cli").mock(
                    return_value=httpx.Response(200, json={
                        "rst_types": "text", "rst_data": {"status": "ok", "result": 999}, "rst_err": ""}))
                try:
                    await client.call("AI:tc-math;eval,2+2", alias="msllm")
                except Exception:
                    pass
                # 不降级：rank2 未被调用（respx 记录 0 次）
                called2 = [c for c in respx.calls if "mock-tc2" in str(c.request.url)]
                assert len(called2) == 0, "ACCESS_DENIED 不应触发 rank 降级"
            return True
        assert asyncio.run(run())

    def test_unknown_alias_default_fallback(self, seeded_endpoints, monkeypatch):
        """未知 alias → default_alias（home-service）兜底"""
        from app.config import get_config
        from app.services.textcli_enhanced_client import EnhancedTextCliClient

        async def run():
            # config 是 dict——直接改键
            get_config()["runtime_endpoints"] = {"enabled": True, "default_alias": "home-service"}
            client = EnhancedTextCliClient()
            with respx.mock:
                respx.post("http://mock-home:28050/text-cli/cli").mock(
                    return_value=httpx.Response(200, json={
                        "rst_types": "text", "rst_data": {"status": "ok", "result": 7}, "rst_err": ""}))
                r = await client.call("AI:tc-math;eval,1+2*3", alias="unknown")
                assert r.ok and r.data["result"] == 7
            return True
        assert asyncio.run(run())

    def test_discover_directives(self, seeded_endpoints):
        """discover：directives[] 直读"""
        from app.services.textcli_enhanced_client import EnhancedTextCliClient

        async def run():
            client = EnhancedTextCliClient()
            with respx.mock:
                respx.post("http://mock-tc1:28050/text-cli/cli").mock(
                    return_value=httpx.Response(200, json={
                        "rst_types": "text",
                        "rst_data": {"directives": [
                            {"domain": "tc-math", "action": "eval", "usage": "tc-math;eval,<表达式>"}]},
                        "rst_err": ""}))
                directives = await client.discover("json", alias="msllm")
                assert directives[0]["domain"] == "tc-math"
            return True
        assert asyncio.run(run())
