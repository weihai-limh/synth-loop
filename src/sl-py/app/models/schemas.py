"""Pydantic 数据模型定义"""

from typing import Any, Optional

from pydantic import BaseModel, Field


class ChatCompletionRequest(BaseModel):
    """聊天补全请求模型"""

    model: str
    messages: list[dict[str, Any]]
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    top_p: Optional[float] = None
    stream: bool = False  # 一期忽略
    tools: Optional[list[dict[str, Any]]] = None
    tool_choice: Optional[str | dict[str, Any]] = None
    # v0_1_1 Phase 6: packets 数据面
    packets: Optional[list[str]] = None          # packet ID 列表
    inline_data: Optional[list[dict[str, Any]]] = None  # 降级内联数据
    # _a 3.6: 相位 chat 多轮契约——调用方回传（响应携带、原样回传推进）
    synth_pipeline: Optional[dict[str, Any]] = None   # {id, action: confirm|reject|regenerate|...}


class ChatCompletionResponse(BaseModel):
    """聊天补全响应模型"""

    id: str
    object: str = "chat.completion"
    created: int
    model: str
    choices: list[dict[str, Any]]
    usage: dict[str, int]


class ErrorResponse(BaseModel):
    """错误响应模型"""

    error: dict[str, Any] = Field(
        default_factory=lambda: {
            "message": "",
            "type": "",
            "code": 0,
        }
    )


class HealthResponse(BaseModel):
    """健康检查响应模型"""

    status: str = "ok"
    version: str
    active_sessions: int = 0


class ToolDefinition(BaseModel):
    """工具定义模型"""

    name: str
    description: str
    parameters: dict[str, Any]
