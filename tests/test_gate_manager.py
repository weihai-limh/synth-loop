# -*- coding: utf-8 -*-
"""_b P6.3: gate_manager 统一闸测试——闸统一抽象 / 组合注册表 / meta 闸 / 跨内核循环 / HTTP 钩子面

承接 pk/ck 后，闸相关测试从"测 sl 三闸"改为"测 gate_manager 编排 + pk/ck 闸"。
本文件覆盖（组件形态，非 HTTP 代理）：
- GateType 五类 / GateResponse 统一语义
- 预制组合函数注册表 + set_active_combo
- meta 闸（ck 闸开关：on/off/auto → set_gate_mode 转发）
- 跨内核循环 run_cycle（各组合）
- HTTP 钩子面 /gate-manager/config（GET/PATCH，供外挂服务）
"""

import pytest
from fastapi.testclient import TestClient

from app.services.gate_manager import (
    GateManager, GateType, GateResponse,
    MockCkGatePort, MockPkGatePort,
    DEFAULT_COMBOS, get_gate_manager,
)


@pytest.fixture
def gm():
    return GateManager(ck=MockCkGatePort(), pk=MockPkGatePort())


# ── 闸统一抽象 ──

class TestGateAbstraction:
    def test_gate_type_five(self):
        assert GateType.DECISION.value == "decision"
        assert GateType.APPROVAL.value == "approval"
        assert GateType.QUALITY.value == "quality"
        assert GateType.INTERVENTION.value == "intervention"
        assert GateType.META.value == "meta"

    def test_gate_response(self):
        resp = GateResponse(GateType.META.value, "auto", reason="on")
        assert resp.to_dict()["verdict"] == "auto"


# ── 组合注册表 ──

class TestComboRegistry:
    def test_default_combos(self, gm):
        combos = gm.get_combos()
        assert "decision_approval" in combos
        assert "intervention_approval" in combos
        assert "meta_all_on" in combos
        assert "all_off" in combos

    def test_default_active_all_off(self, gm):
        assert gm.get_config()["active_combo"] == "all_off"

    def test_set_active_combo(self, gm):
        gm.set_active_combo("decision_approval")
        assert gm.get_config()["active_combo"] == "decision_approval"

    def test_set_unknown_combo_raises(self, gm):
        with pytest.raises(ValueError):
            gm.set_active_combo("bogus")


# ── meta 闸（ck 闸开关）──

class TestMetaGate:
    def test_meta_on_maps_auto(self, gm):
        r = gm.set_meta_gate("on")
        assert r.verdict == "auto"  # on → auto
        assert gm.ck._mode == "auto"  # 转发到 ck set_gate_mode

    def test_meta_off_maps_closed(self, gm):
        r = gm.set_meta_gate("off")
        assert r.verdict == "closed"
        assert gm.ck._mode == "closed"

    def test_meta_invalid(self, gm):
        r = gm.set_meta_gate("bogus")
        assert r.verdict == "invalid"

    def test_meta_no_ck(self):
        g = GateManager()  # 无 ck
        r = g.set_meta_gate("on")
        assert r.verdict == "no_ck"


# ── 跨内核循环 ──

class _FakePhase:
    path = [0, 0]
    status = "awaiting_approval"
    name = "ph0"


class TestRunCycle:
    def test_all_off_empty(self, gm):
        gm.set_active_combo("all_off")
        assert gm.run_cycle() == []

    def test_decision_only(self, gm):
        gm.set_active_combo("decision_only")
        stack = gm.run_cycle(phase=_FakePhase())
        assert [g.verdict for g in stack] == ["query"]

    def test_meta_all_on(self, gm):
        gm.set_active_combo("meta_all_on")
        gm.set_meta_gate("on")
        stack = gm.run_cycle(context_id="c1", phase=_FakePhase())
        verdicts = [g.verdict for g in stack]
        assert "applied" in verdicts  # meta 应用

    def test_intervention_approval(self, gm):
        gm.set_active_combo("intervention_approval")
        stack = gm.run_cycle(context_id="c1", phase=_FakePhase(), custom_context={"x": 1})
        verdicts = [g.verdict for g in stack]
        assert "unpark" in verdicts   # intervention（peek→amend）
        assert "pending" in verdicts  # approval 查询

    def test_cycle_stack_type(self, gm):
        gm.set_active_combo("decision_approval")
        stack = gm.run_cycle(phase=_FakePhase())
        assert all(isinstance(g, GateResponse) for g in stack)


# ── HTTP 钩子面（/gate-manager/config）──

class TestGateHttp:
    def test_get_config(self):
        from app.main import app
        with TestClient(app) as client:
            r = client.get("/gate-manager/config")
            assert r.status_code == 200
            cfg = r.json()
            assert "combos" in cfg and "active_combo" in cfg and "meta_gate" in cfg

    def test_patch_active_combo(self):
        from app.main import app
        with TestClient(app) as client:
            r = client.patch("/gate-manager/config", json={"active_combo": "decision_approval"})
            assert r.status_code == 200
            assert r.json()["active_combo"] == "decision_approval"

    def test_patch_meta_gate(self):
        from app.main import app
        with TestClient(app) as client:
            r = client.patch("/gate-manager/config", json={"meta_gate": "on"})
            assert r.status_code == 200
            assert r.json()["meta_gate"] == "auto"

    def test_patch_invalid_combo_400(self):
        from app.main import app
        with TestClient(app) as client:
            r = client.patch("/gate-manager/config", json={"active_combo": "bogus"})
            assert r.status_code == 400
