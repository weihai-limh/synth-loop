"""ck 公开 API 重导出（双形态共用同一份导出，design §2.3 / dev-plan §0.4）。

组件形态（import 即用）与 serve 外挂形态共用同一导出集合。
"""

from .core.models import (
    AssembledContext,
    ContextPatch,
    CustomContext,
    GateMode,
    InferenceResult,
    SessionView,
)
from .core.context_kernel import ContextKernel
from .core.assembler import build_passthrough, build_prompt
from .core.gate import GatePark, extract_custom_context, reassemble_from_custom
from .core.gate_config import GateConfig
from .ports import ContextSource, DataPlane, LlmProvider
from .adapters.noop_data_plane import NoOpDataPlane
from .adapters.mock_llm import MockLlmProvider
from .serve.session_store import SessionStore

__all__ = [
    # 数据模型
    "SessionView",
    "ContextPatch",
    "InferenceResult",
    "AssembledContext",
    "CustomContext",
    "GateMode",
    # 标准运行时
    "ContextKernel",
    "build_prompt",
    "build_passthrough",
    # 推理闸
    "GatePark",
    "extract_custom_context",
    "reassemble_from_custom",
    "GateConfig",
    # 三端口
    "ContextSource",
    "DataPlane",
    "LlmProvider",
    # adapters（占位/测试）
    "NoOpDataPlane",
    "MockLlmProvider",
    # serve 层
    "SessionStore",
]
