"""pytest fixtures for synth-loop tests (v0_1_2)"""

import os
import sys
import tempfile
import pytest
from pathlib import Path

# Ensure src/ is in path for true imports
SRC_DIR = Path(__file__).resolve().parent.parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))


@pytest.fixture
def temp_db_path(tmp_path):
    """临时 SQLite 数据库路径"""
    db_path = tmp_path / "test_gateway.db"
    return str(db_path)


@pytest.fixture
def temp_config_dir(tmp_path):
    """临时配置目录，覆盖 SRC_DIR/config 解析"""
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    return str(config_dir)


@pytest.fixture
def sample_plan_config():
    """示例 PlanConfig 数据"""
    return {
        "phases": [
            {
                "index": 1,
                "name": "需求分析",
                "description": "分析用户需求并产出需求文档",
                "mode": "single_ai",
                "mode_params": None,
                "gates": {
                    "show_terminal": True,
                    "allow_path_edit": False,
                    "require_human_approval": False,
                },
            },
            {
                "index": 2,
                "name": "方案设计",
                "description": "设计技术方案",
                "mode": "single_ai_human_review",
                "mode_params": None,
                "gates": {
                    "show_terminal": True,
                    "allow_path_edit": True,
                    "require_human_approval": True,
                },
            },
        ]
    }


# ═══ _a P1.1：SPEC 1.3.2 mock 契约（P15 对齐） ═══

@pytest.fixture
def mock_textcli():
    """Mock text-cli——SPEC 1.3.2 信封：rst_data 直读、--async pending+task_id、task.state 五态。

    - POST /text-cli/cli：根据 prompt 区分同步执行 / --async 委托 / 错误信封
    - GET  /text-cli/tasks/{id}：task.state 五态轮询
    """
    import respx
    import httpx

    with respx.mock(assert_all_called=False) as mock:
        # 同步执行：rst_data 直读（不再 .text 嵌套）
        mock.post("http://localhost:28050/text-cli/cli").mock(
            side_effect=lambda req: _mock_cli_post(req)
        )
        # 异步轮询：task.state 五态
        mock.get(url__regex=r"http://localhost:28050/text-cli/tasks/(.+)").mock(
            side_effect=lambda req: _mock_task_poll(req)
        )
        yield mock


def _mock_cli_post(req):
    import httpx
    body = req.content.decode("utf-8", errors="ignore")
    if "--async" in body:
        # 异步委托：{"status":"pending","task_id":...} 直读（SPEC §1.2.2）
        return httpx.Response(200, json={
            "rst_types": "text",
            "rst_data": {"status": "pending", "task_id": "tc-async-001"},
            "rst_err": "",
        })
    if "text-cli;query" in body:
        # 指令发现：directives[] 直读（SPEC §1.2.7）
        return httpx.Response(200, json={
            "rst_types": "text",
            "rst_data": {"directives": [
                {"domain": "tc-math", "action": "eval",
                 "usage": "tc-math;eval,<表达式>", "params": ["expression"]}
            ]},
            "rst_err": "",
        })
    if "nonexistent" in body:
        # 错误信封：rst_err 闭集（SPEC §1.2.8）
        return httpx.Response(200, json={
            "rst_types": "text",
            "rst_data": {"status": "error", "reason": "directive not found"},
            "rst_err": "ERR_NOT_FOUND",
        })
    # 默认同步成功
    return httpx.Response(200, json={
        "rst_types": "text",
        "rst_data": {"status": "ok", "result": 4},
        "rst_err": "",
    })


def _mock_task_poll(req):
    import httpx
    # task.state 五态（SPEC §1.2.6）——done 时含 result
    return httpx.Response(200, json={
        "status": "ok",
        "task": {"task_id": "tc-async-001", "state": "done",
                 "result": {"output": "phase result"}, "progress": "步骤 3/8"},
    })


@pytest.fixture
def mock_strata_match():
    """Mock strata-match——tools[] 含 endpoint_alias/estimated_time（_a 契约锚）"""
    import respx
    import httpx

    with respx.mock(assert_all_called=False) as mock:
        mock.post("http://localhost:13156/api/v1/query").mock(
            return_value=httpx.Response(200, json={
                "primary_prompt": "test strategy prompt",
                "matched_tags": ["test"],
                "tools": [{
                    "usage": "bd-map;geocode",
                    "name": "bd-map-geocode",
                    "command": "AI:bd-map;geocode,<address>",
                    "endpoint_alias": "home-service",
                    "estimated_time": "3s",
                }],
                "assets": [],
            })
        )
        yield mock
