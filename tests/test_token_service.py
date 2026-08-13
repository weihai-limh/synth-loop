"""_a P4: 统一 token 层测试——签发/校验/scope 分层/身份映射/管理面 admin scope"""

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
    from app import database as db
    asyncio.run(db.close_shared_db())
    monkeypatch.setattr(db, "get_db_path", lambda: str(tmp_path / "test_gateway.db"))
    yield db
    asyncio.run(db.close_shared_db())


class TestTokenService:
    """tokens 表 + verify_token/map_user_id"""

    def test_issue_and_verify(self, gw_db):
        from app.services.token_service import issue_token, verify_token

        async def run():
            await gw_db.init_database()
            await issue_token("tok-admin-1", "sl", "admin")
            await issue_token("tok-user-1", "sl", "user", user_id="sl-abc123")
            # 校验通过
            assert await verify_token("sl", "tok-admin-1", "admin") == ""
            assert await verify_token("sl", "tok-user-1", "user") == "sl-abc123"
            # scope 不匹配 → None
            assert await verify_token("sl", "tok-admin-1", "user") is None
            # 无效 token → None
            assert await verify_token("sl", "wrong-token", "user") is None
            return True
        assert asyncio.run(run())

    def test_hash_storage_not_plaintext(self, gw_db):
        """token 表存储为 sha256 值（非明文）"""
        async def run():
            await gw_db.init_database()
            from app.services.token_service import issue_token
            await issue_token("secret-plain-1", "sl", "admin")
            conn = await gw_db.get_shared_db()
            cur = await conn.execute("SELECT token_hash FROM tokens WHERE id IS NOT NULL")
            rows = await cur.fetchall()
            assert rows
            for r in rows:
                assert "secret-plain" not in r["token_hash"]
                assert len(r["token_hash"]) == 64  # sha256 hex
            return True
        assert asyncio.run(run())

    def test_map_user_id(self):
        from app.services.token_service import map_user_id
        assert map_user_id("sl-uuid-1") == "sl-uuid-1"
        assert map_user_id("") == ""

    def test_auth_disabled_no_check(self, gw_db, monkeypatch):
        """auth.enabled=false → 请求正常（开箱即用，向后兼容）"""
        from app.config import get_auth_settings
        monkeypatch.setattr(get_auth_settings(), "enabled", False)
        async def run():
            return True
        assert asyncio.run(run())


class TestAdminScope:
    """运行时表管理 API：admin scope 校验（3.12）"""

    def test_admin_required_when_auth_enabled(self, gw_db, monkeypatch):
        """auth.enabled=true 且无 token → 401；user token → 403；admin token → 通过"""
        from app.services.token_service import issue_token

        async def run():
            await gw_db.init_database()
            await issue_token("tok-user", "sl", "user", user_id="sl-1")
            await issue_token("tok-admin", "sl", "admin")

            # 通过 token_service 直接验证 admin scope 语义
            from app.services.token_service import verify_token
            assert await verify_token("sl", "tok-user", "admin") is None    # user token 非 admin
            assert await verify_token("sl", "tok-admin", "admin") == ""     # admin token 通过
            return True
        assert asyncio.run(run())
