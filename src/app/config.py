"""配置管理模块"""

import logging
import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel

logger = logging.getLogger(__name__)

# ── 项目路径常量 ──────────────────────────────────────────
# src/app/config.py → .parent=src/app/ → .parent.parent=src/ → .parent.parent.parent=项目根
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SRC_DIR = PROJECT_ROOT / "src"
DATA_DIR = SRC_DIR / "data"
DEPLOY_DIR = PROJECT_ROOT / "deploy"
CONFIG_DIR = SRC_DIR / "config"

# ── v0_1_2: Fractal Prompt 配置化 ─────────────────────────
FRACTAL_PROMPT_PATH = CONFIG_DIR / "fractal_prompt.txt"

# 内置默认值（文件不存在时的回退）
_FRACTAL_PROMPT_DEFAULT = (
    "Always use the same language as the user's latest message unless user explicitly asks.\n\n"
    "You are a request classifier. Respond with EXACTLY ONE letter:\n\n"
    "a - Simple greeting, weather, chit-chat. Direct answer, no enhancement.\n"
    "b - Professional task (writing, coding, analysis). Needs prompt enhancement.\n"
    "c - Single external tool or agent call.\n"
    "d - Single synchronous task. Quick to complete, immediate response.\n"
    "e - Multi-step task chain. Plan → execute → verify → summarize.\n"
    "f - Synchronous task chain. All steps complete quickly.\n\n"
    'User message: """{user_message}"""\n\n'
    "Respond with ONLY the letter, nothing else."
)


def load_fractal_prompt() -> str:
    """v0_1_2: 从文件加载分形分类 Prompt，文件不存在时使用内置默认 + WARNING"""
    if FRACTAL_PROMPT_PATH.exists():
        with open(FRACTAL_PROMPT_PATH, "r", encoding="utf-8") as f:
            return f.read()
    logger.warning(f"Fractal prompt file not found: {FRACTAL_PROMPT_PATH}, using built-in default")
    return _FRACTAL_PROMPT_DEFAULT


def load_config(config_path: str | Path | None = None) -> dict[str, Any]:
    """加载配置文件。config_path 为 None 时从 src/config.yaml 加载"""
    if config_path is None:
        config_path = SRC_DIR / "config.yaml"
    config_path = Path(config_path)
    if not config_path.exists():
        raise FileNotFoundError(f"配置文件不存在: {config_path}")

    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    # 处理环境变量替换
    config = _resolve_env_vars(config)
    return config


def _resolve_env_vars(obj: Any) -> Any:
    """递归解析配置中的环境变量"""
    if isinstance(obj, str):
        if obj.startswith("${") and obj.endswith("}"):
            env_var = obj[2:-1]
            return os.environ.get(env_var, obj)
        return obj
    elif isinstance(obj, dict):
        return {k: _resolve_env_vars(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_resolve_env_vars(item) for item in obj]
    return obj


# 全局配置实例
_config: dict[str, Any] | None = None


def get_config() -> dict[str, Any]:
    """获取全局配置"""
    global _config
    if _config is None:
        _config = load_config()
    return _config


def get_section(section: str) -> dict[str, Any]:
    """获取配置的某个部分"""
    config = get_config()
    if section not in config:
        raise KeyError(f"配置项不存在: {section}")
    return config[section]


# ═══════════════════════════════════════════════════════════
# v0_1_1 新增 Pydantic 配置模型（增量——旧段仍用 get_section）
# ═══════════════════════════════════════════════════════════

class AuthSettings(BaseModel):
    """用户认证配置"""
    enabled: bool = False
    required: bool = False


class SessionMemorySettings(BaseModel):
    """会话记忆配置"""
    enabled: bool = True


class AsyncTaskSettings(BaseModel):
    """异步任务配置"""
    enabled: bool = False
    max_per_user: int = 3


class PacketsSettings(BaseModel):
    """packets API 配置"""
    enabled: bool = True
    ttl_seconds: int = 1800
    max_packet_size_mb: int = 5
    max_packets_per_request: int = 20
    max_inline_data_per_request: int = 10


def get_auth_settings() -> AuthSettings:
    """获取认证配置（带类型校验）"""
    config = get_config()
    return AuthSettings(**config.get("auth", {}))


def get_session_memory_settings() -> SessionMemorySettings:
    """获取会话记忆配置（带类型校验）"""
    config = get_config()
    return SessionMemorySettings(**config.get("session_memory", {}))


def get_async_task_settings() -> AsyncTaskSettings:
    """获取异步任务配置（带类型校验）"""
    config = get_config()
    return AsyncTaskSettings(**config.get("async_tasks", {}))


def get_packets_settings() -> PacketsSettings:
    """获取 packets API 配置（带类型校验）"""
    config = get_config()
    return PacketsSettings(**config.get("packets", {}))
