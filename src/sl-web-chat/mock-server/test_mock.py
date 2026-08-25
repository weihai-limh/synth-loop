# 7.0 mock 冒烟：断言端点 response 符合 api_zh.md 契约（即前端可正确消费）
import json
import pytest
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)
SID = "s_demo"   # mock 默认会话，预置数据可见


def test_health():
    assert client.get("/health").json()["mock"] is True


def test_chat_plain():
    r = client.post("/v1/chat/completions", json={"messages": [{"role": "user", "content": "hi"}]})
    assert r.status_code == 200
    data = r.json()
    assert data["choices"][0]["message"]["role"] == "assistant"
    assert "content" in data["choices"][0]["message"]


def test_phase_flow():
    # 首轮触发
    r1 = client.post("/v1/chat/completions", json={
        "messages": [{"role": "user", "content": "<tc-phase>做市场调研报告</tc-phase>"}]})
    p1 = r1.json()["synth_pipeline"]
    assert p1["step"] == "awaiting_plan_confirm"
    assert p1["artifact_ref"] == "art_p1_plan"
    pid = p1["id"]
    # 确认 plan → path
    r2 = client.post("/v1/chat/completions", json={
        "messages": [{"role": "user", "content": "确认"}],
        "synth_pipeline": {"id": pid, "action": "confirm"}})
    p2 = r2.json()["synth_pipeline"]
    assert p2["step"] == "awaiting_path_confirm"
    assert p2["artifact_ref"] == "art_p1_path_0"
    # 确认 path → approval
    r3 = client.post("/v1/chat/completions", json={
        "messages": [{"role": "user", "content": "确认"}],
        "synth_pipeline": {"id": pid, "action": "confirm"}})
    p3 = r3.json()["synth_pipeline"]
    assert p3["step"] == "awaiting_approval"
    # 确认 approval → completed
    r4 = client.post("/v1/chat/completions", json={
        "messages": [{"role": "user", "content": "确认"}],
        "synth_pipeline": {"id": pid, "action": "confirm"}})
    p4 = r4.json()["synth_pipeline"]
    assert p4["step"] == "completed"


def test_ck_gate():
    # 触发 park
    r1 = client.post("/v1/chat/completions", json={
        "messages": [{"role": "user", "content": "推理一下 <gate>某问题</gate>"}]})
    d1 = r1.json()
    assert d1["gate"] == "pending"
    cid = d1["context_id"]
    # peek
    peek = client.get(f"/chatgate/{cid}")
    assert peek.status_code == 200
    # amend
    am = client.post(f"/chatgate/{cid}", json={"context": {"region_index": 2, "fixed": True}})
    assert am.json()["amended"] is True
    # 放行出结果（mock 用 amended_ok 标记）
    r2 = client.post("/v1/chat/completions", json={"messages": [{"role": "user", "content": "继续"}]})
    assert "放行" in r2.json()["choices"][0]["message"]["content"]


def test_packets():
    r = client.post("/v1/packets", json={"source": "sl-web-chat", "type": "doc", "payload": {"data": "x"}})
    assert r.status_code == 200
    assert r.json()["packet_id"].startswith("pkt_")


def test_longdata_crud():
    # 预置可见
    lst = client.get("/v1/longdata", params={"session_id": SID})
    assert len(lst.json()["items"]) >= 2
    # 增
    add = client.post("/v1/longdata", json={"session_id": SID, "type": "doc", "content": "新条目"})
    lid = add.json()["id"]
    assert lid.startswith("ld_")
    # 删
    dele = client.delete(f"/v1/longdata/{lid}", params={"session_id": SID})
    assert dele.json()["deleted"] is True
    # 删不存在
    dele2 = client.delete(f"/v1/longdata/ld_nope", params={"session_id": SID})
    assert dele2.json()["deleted"] is False


def test_artifacts():
    a = client.get("/api/v1/artifacts/art_p1_plan")
    assert a.status_code == 200
    assert "content" in a.json() and "data" in a.json()
    lst = client.get("/api/v1/artifacts", params={"pipeline_id": "p1"})
    assert len(lst.json()["items"]) >= 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
