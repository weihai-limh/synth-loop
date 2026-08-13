"""_a P2.1: 运行时表测试——种子幂等 / CRUD / token 脱敏 / rank 降级 / default_alias"""

import asyncio
import os
import sys
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))


@pytest.fixture
def gw_db(tmp_path, monkeypatch):
    """隔离 gateway.db：临时路径 + close 全局连接"""
    from app import database as db
    asyncio.run(db.close_shared_db())
    monkeypatch.setattr(db, "get_db_path", lambda: str(tmp_path / "test_gateway.db"))
    os.environ["SELF_TOKEN_ENC_KEY"] = "test-enc-key-for-runtime"
    yield db
    asyncio.run(db.close_shared_db())


class TestRuntimeEndpoints:
    """运行时表（配置面）"""

    def test_seed_idempotent(self, gw_db):
        """种子灌入幂等（重复 init 不重复插入）"""
        from app.services.runtime_endpoints import seed_runtime_endpoints

        async def run():
            await gw_db.init_database()
            config = {"runtime_endpoints": {
                "enabled": True,
                "default_alias": "home-service",
                "seeds": [
                    {"alias": "home-service", "url": "http://h:28050/text-cli/cli", "rank": 1},
                    {"alias": "cloud", "url": "https://c/text-cli/cli", "rank": 2},
                ],
            }}
            await seed_runtime_endpoints(config)
            await seed_runtime_endpoints(config)  # 二次
            conn = await gw_db.get_shared_db()
            cur = await conn.execute("SELECT COUNT(*) AS c FROM runtime_endpoints")
            assert (await cur.fetchone())["c"] == 2
            return True
        assert asyncio.run(run())

    def test_token_encrypted_and_masked(self, gw_db):
        """token 落库加密（非明文）+ 列表脱敏返回"""
        from app.services.runtime_endpoints import create_endpoint, list_endpoints

        async def run():
            await gw_db.init_database()
            await create_endpoint({"alias": "ep1", "url": "http://e:28050/text-cli/cli",
                                   "auth": "single", "service_token": "sk-super-secret"})
            conn = await gw_db.get_shared_db()
            cur = await conn.execute("SELECT service_token FROM runtime_endpoints WHERE alias='ep1'")
            row = await cur.fetchone()
            stored = row["service_token"]
            assert stored != "sk-super-secret"  # 加密存储
            eps = await list_endpoints()
            ep = next(e for e in eps if e["alias"] == "ep1")
            assert ep["service_token"] != "sk-super-secret"  # 脱敏
            assert "***" in ep["service_token"]
            return True
        assert asyncio.run(run())

    def test_crud(self, gw_db):
        """CRUD 正常"""
        from app.services.runtime_endpoints import (
            create_endpoint, update_endpoint, delete_endpoint, list_endpoints,
        )

        async def run():
            await gw_db.init_database()
            await create_endpoint({"alias": "ep", "url": "http://e:28050/text-cli/cli", "rank": 3})
            up = await update_endpoint("ep", {"rank": 5})
            assert up[0]["rank"] == 5
            ok = await delete_endpoint("ep")
            assert ok
            assert len(await list_endpoints()) == 0
            return True
        assert asyncio.run(run())

    def test_resolve_alias_rank_order(self, gw_db):
        """同 alias 多物理行按 rank 递增（降级链数据基础）"""
        from app.services.runtime_endpoints import create_endpoint, resolve_alias

        async def run():
            await gw_db.init_database()
            await create_endpoint({"alias": "msllm", "url": "http://a:28050/text-cli/cli", "rank": 2})
            await create_endpoint({"alias": "msllm", "url": "http://b:28050/text-cli/cli", "rank": 1})
            rows = await resolve_alias("msllm")
            assert [r["url"] for r in rows] == ["http://b:28050/text-cli/cli", "http://a:28050/text-cli/cli"]
            return True
        assert asyncio.run(run())

    def test_resolve_unknown_alias_fallback_default(self, gw_db, monkeypatch):
        """未知 alias → default_alias 兜底；无 alias → rank 最小"""
        from app.services.runtime_endpoints import create_endpoint, resolve_alias

        async def run():
            await gw_db.init_database()
            await create_endpoint({"alias": "home", "url": "http://h:28050/text-cli/cli", "rank": 10})
            await create_endpoint({"alias": "fast", "url": "http://f:28050/text-cli/cli", "rank": 1})
            # 未知 alias + default_alias=home
            rows = await resolve_alias("nope", default_alias="home")
            assert rows[0]["alias"] == "home"
            # 无 alias 无 default → rank 最小
            rows2 = await resolve_alias(None, default_alias=None)
            assert rows2[0]["alias"] == "fast"
            return True
        assert asyncio.run(run())
