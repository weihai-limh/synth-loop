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
