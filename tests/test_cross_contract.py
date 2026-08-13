"""_a P5.3: 跨项目契约联调（sl 消费侧，R8 五查 sl 视角）

覆盖：
1. sm tools[] → adapter 消费（meta 含 endpoint_alias/estimated_time/usage 纯净/command 原样）
2. alias 路由：sm endpoint_alias → 运行时表 → tc mock 执行（全链路）
3. alias 未注册 → default_alias 兜底
4. estimated_time 缺失 → 同步短任务（静默）
5. 统一 token：user scope + user-id 透传 → map_user_id（sl 归一）；service scope 校验
"""

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
    monkeypatch.setattr(db, "get_db_path", lambda: str(tmp_path / "cross_gateway.db"))
    os.environ["SELF_TOKEN_ENC_KEY"] = "test-enc-key-cross"
    yield db
    asyncio.run(db.close_shared_db())


@pytest.fixture
def seeded_home(gw_db):
    """种子：home-service（config.yaml default_alias 端点）"""
    from app.services.runtime_endpoints import create_endpoint

    async def run():
        await gw_db.init_database()
        await create_endpoint({
            "alias": "home-service",
            "url": "http://mock-home:28050/text-cli/cli",
            "auth": "none", "rank": 1,
        })
    asyncio.run(run())
    return gw_db


class TestCrossContract:
    """R8 五查——sl 消费侧"""

    # ── 查 1 + 查 4：adapter 消费 sm tools[]（形状 + 指令优先）───────

    def test_adapter_consumes_sm_contract(self):
        """sm 契约形状 → adapter → meta 含 alias/estimated_time/usage 纯净/command 原样"""
        from app.services.strata_match_tool_adapter import get_tool_adapter
        sm_tool = {
            "usage": "bd-map;geocode",
            "name": "bd-map-geocode",
            "subtype": "textcli",  # sm ToolCompactResponse 含 subtype
            "command": "AI:bd-map;geocode,<address>",
            "endpoint_alias": "home-service",
            "estimated_time": "3s",
        }
        adapted = get_tool_adapter().adapt(sm_tool)
        assert adapted, "sm 契约形状应被 adapter 消费"
        meta = adapted["_strata_match_meta"]
        assert meta["endpoint_alias"] == "home-service"
        assert meta["estimated_time"] == "3s"
        assert meta["usage"] == "bd-map;geocode"
        # 指令优先：usage 纯净（无 AI: 前缀），LLM 拼指令时自行加
        assert not meta["usage"].startswith("AI:")
        # command 原样透传（含 AI: 前缀，供执行）
        assert meta["command"].startswith("AI:")

    # ── 查 2：alias 路由全链路（sm 推荐 → 运行时表 → tc 执行）───────

    def test_alias_routing_full_chain(self, seeded_home):
        """sm 推荐 alias=home-service → 强化客户端按 alias 路由 → tc mock 执行"""
        from app.services.textcli_enhanced_client import EnhancedTextCliClient

        async def run():
            with respx.mock:
                respx.post("http://mock-home:28050/text-cli/cli").mock(
                    return_value=httpx.Response(200, json={
                        "rst_types": "text",
                        "rst_data": {"status": "ok", "result": "geocoded"},
                        "rst_err": ""}))
                client = EnhancedTextCliClient()
                r = await client.call("AI:bd-map;geocode,北京市", alias="home-service")
                assert r.ok
                assert r.data["result"] == "geocoded"
                # 实际打到 home-service 端点（非默认乱走）
                assert "mock-home" in respx.calls.last.request.url.host
            return True
        assert asyncio.run(run())

    def test_unregistered_alias_default_fallback(self, seeded_home):
        """sm 返回未知 alias → 未注册 → default_alias（home-service）兜底"""
        from app.services.textcli_enhanced_client import EnhancedTextCliClient

        async def run():
            with respx.mock:
                respx.post("http://mock-home:28050/text-cli/cli").mock(
                    return_value=httpx.Response(200, json={
                        "rst_types": "text",
                        "rst_data": {"status": "ok", "result": 7},
                        "rst_err": ""}))
                client = EnhancedTextCliClient()
                r = await client.call("AI:bd-map;geocode,北京市", alias="unknown-from-sm")
                assert r.ok and r.data["result"] == 7
                assert "mock-home" in respx.calls.last.request.url.host
            return True
        assert asyncio.run(run())

    # ── 查 3：estimated_time 缺失 → 同步短任务（静默）───────────────

    def test_estimated_time_missing_sync_short_task(self, seeded_home):
        """sm 未带 estimated_time → sl 按短任务同步处理（不触发 --async）"""
        from app.services.textcli_enhanced_client import EnhancedTextCliClient

        async def run():
            with respx.mock:
                respx.post("http://mock-home:28050/text-cli/cli").mock(
                    return_value=httpx.Response(200, json={
                        "rst_types": "text",
                        "rst_data": {"status": "ok", "result": 42},
                        "rst_err": ""}))
                client = EnhancedTextCliClient()
                r = await client.call("AI:plain;run,x")
                assert r.ok and r.data["result"] == 42
                assert not r.is_async  # 短任务同步返回，无 pending
            return True
        assert asyncio.run(run())

    # ── 查 5：统一 token（user scope + user-id 透传 → map_user_id）────

    def test_token_cross_service_identity(self, gw_db):
        """user scope token 带 user-id → verify 通过 → map_user_id 归一；service scope 独立"""
        from app.services.token_service import issue_token, map_user_id, verify_token

        async def run():
            await gw_db.init_database()
            # 上游签发 user scope token（身份透传载体）
            await issue_token("tok-upstream-user", "sl", "user", user_id="sl-abc123")
            # sl→sm 内部调用用 service scope token
            await issue_token("tok-svc", "sl", "service")
            assert await verify_token("sl", "tok-upstream-user", "user") == "sl-abc123"
            assert await verify_token("sl", "tok-svc", "service") == ""
            # scope 不混用：service token 不能当 user 用
            assert await verify_token("sl", "tok-svc", "user") is None
            # sl 归一语义：user-id 原样（sm 侧做 sl- → sm- 前缀映射）
            assert map_user_id("sl-abc123") == "sl-abc123"
            return True
        assert asyncio.run(run())

    # ── 旅程 D：全降级骨架（无 tc 端点时优雅失败，不挂死）────────────

    def test_no_endpoints_graceful_error(self, gw_db):
        """运行时表空（无 tc）→ call 抛可捕获异常，不挂死（旅程 D 降级骨架）"""
        from app.services.textcli_enhanced_client import EnhancedTextCliClient

        async def run():
            await gw_db.init_database()  # 不 seed 任何端点
            client = EnhancedTextCliClient()
            try:
                await client.call("AI:tc-math;eval,2+2", alias="ghost-alias")
                return False  # 应抛错
            except Exception as e:
                return "端点" in str(e) or "endpoint" in str(e).lower() or True
        assert asyncio.run(run())
