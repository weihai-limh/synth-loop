"""_a P1.1: mock 契约对齐 SPEC 1.3.2（P15 验收）

验证 mock fixtures 返回的信封形状与真实 tc 契约一致：
- rst_data 直读（不再 .text 嵌套）
- --async 响应 {"status":"pending","task_id":...}
- 轮询 task.state 五态
- 错误信封 rst_err 闭集
- sm tools[] 含 endpoint_alias/estimated_time（契约锚）
"""

import httpx
import pytest


class TestMockTextcliContract:
    """Mock text-cli 信封形状（SPEC 1.3.2）"""

    def test_sync_call_rst_data_direct(self, mock_textcli):
        """同步执行：rst_data 直读（无 .text 嵌套）——P15 核心"""
        resp = httpx.post("http://localhost:28050/text-cli/cli",
                          json={"prompt": "AI:tc-math;eval,2+2"})
        body = resp.json()
        assert body["rst_types"] == "text"
        assert body["rst_err"] == ""
        # 直读 rst_data，无 {"text": ...} 嵌套
        assert "text" not in body["rst_data"]
        assert body["rst_data"]["status"] == "ok"

    def test_async_call_pending_task_id(self, mock_textcli):
        """--async 委托：rst_data 含 status=pending + task_id（SPEC §1.2.2）"""
        resp = httpx.post("http://localhost:28050/text-cli/cli",
                          json={"prompt": "AI:text-cli;path,{...},--async"})
        body = resp.json()
        assert body["rst_data"]["status"] == "pending"
        assert body["rst_data"]["task_id"] == "tc-async-001"
        assert body["rst_err"] == ""

    def test_discover_directives_direct(self, mock_textcli):
        """指令发现：rst_data.directives[] 直读（SPEC §1.2.7）"""
        resp = httpx.post("http://localhost:28050/text-cli/cli",
                          json={"prompt": "AI:text-cli;query,json"})
        body = resp.json()
        assert "directives" in body["rst_data"]
        d = body["rst_data"]["directives"][0]
        assert d["domain"] == "tc-math" and d["action"] == "eval"
        assert d["usage"].startswith("tc-math;")  # 无 AI: 前缀

    def test_error_envelope_rst_err_closed_set(self, mock_textcli):
        """错误信封：rst_err 闭集（SPEC §1.2.8），业务原因走 rst_data.reason"""
        resp = httpx.post("http://localhost:28050/text-cli/cli",
                          json={"prompt": "AI:nonexistent;action"})
        body = resp.json()
        assert body["rst_err"] == "ERR_NOT_FOUND"
        assert body["rst_data"]["reason"] == "directive not found"

    def test_task_poll_state_five_states(self, mock_textcli):
        """异步轮询：task.state 五态（SPEC §1.2.6）——非响应信封 status"""
        resp = httpx.get("http://localhost:28050/text-cli/tasks/tc-async-001")
        body = resp.json()
        assert body["status"] == "ok"          # 响应信封 status
        assert "task" in body
        task = body["task"]
        assert task["state"] in {"pending", "running", "done", "error", "cancelled"}
        assert task["task_id"] == "tc-async-001"
        assert task["state"] == "done"
        assert task["result"]["output"] == "phase result"


class TestMockStrataMatchContract:
    """Mock strata-match tools[] 形状（契约锚，供 sl P1.1 消费）"""

    def test_tools_include_contract_fields(self, mock_strata_match):
        """tools[] 含 usage/command/endpoint_alias/estimated_time"""
        resp = httpx.post("http://localhost:13156/api/v1/query",
                          json={"user_ask": "test", "types": "role_play"})
        body = resp.json()
        assert body["primary_prompt"] == "test strategy prompt"
        tools = body["tools"]
        assert tools, "tools[] 不应为空"
        tool = tools[0]
        assert tool["usage"] == "bd-map;geocode"       # domain;action，无 AI:
        assert tool["command"] == "AI:bd-map;geocode,<address>"  # 占位指令原样
        assert tool["endpoint_alias"] == "home-service"  # _a 可选
        assert tool["estimated_time"] == "3s"            # _a 可选
