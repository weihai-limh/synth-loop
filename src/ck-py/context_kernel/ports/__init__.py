"""ck 三端口契约（ports/__init__.py）——零实现、零外部依赖（仅标准库 + 自身）。

design §2.1 / dev-plan §0.2：
- ContextSource：只读（红线⑥只禁闸 set；端口甚至不提供写方法）。
- DataPlane：相位/步骤产物存储与获取（与 ContextSource 分离）。
- LlmProvider：下游 LLM 调用。
"""

from __future__ import annotations

from typing import Any, Optional, Protocol, runtime_checkable

from ..core.models import SessionView


@runtime_checkable
class ContextSource(Protocol):
    """会话只读源（design §2.1）。

    仅暴露只读 read_session；不提供写方法——
    红线⑥"Session 永不被闸改写"的代码级保证（闸 set 只改 park 快照）。
    """

    def read_session(self, session_id: str) -> SessionView:
        """读取会话只读视图（拼装/闸用）。"""
        ...


@runtime_checkable
class DataPlane(Protocol):
    """数据面前序/产物面（design §1.6 / §6.3）。

    与 ContextSource 分离：前者管相位/步骤产物，后者管会话快照。
    """

    def store(self, pipeline_id: str, ref: str, data: Any) -> Any:
        """存储产物（store）。"""
        ...

    def fetch(self, ref: str) -> dict[str, Any]:
        """按 ref 拉取产物（fetch）；NoOp 实现返回空 dict。"""
        ...

    def transfer(self, pipeline_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        """透传/拉取转存分流（transfer）。"""
        ...


@runtime_checkable
class LlmProvider(Protocol):
    """下游 LLM 调用端口（design §2.1 / §6.1）。

    chat(messages, model, stream, service_name=None) -> response；模型由
    primary_model/fallback_model 配置驱动。service_name 为可选服务标识，
    不传（None）时按各实现既有默认回落（D1 已决：显式参数优于隐式塞入
    model 字符串，与「模型选择语义归 sl 分形家族、ck 透明转发」收口一致）。
    """

    def chat(
        self,
        messages: list[dict[str, Any]],
        model: str,
        stream: bool = False,
        service_name: Optional[str] = None,
    ) -> Any:
        """调用下游 LLM，返回响应。service_name 缺省 None 按实现默认。"""
        ...
