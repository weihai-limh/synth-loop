"""ck 数据模型（core/models.py）——零外部依赖（仅标准库 + 自身）。

本模块承载 design §5.5 / dev-plan §0.1 的全部数据类：
SessionView / ContextPatch / InferenceResult / AssembledContext /
CustomContext / GateMode。

所有类型均可 to_dict / from_dict 序列化（验证标准 0.1），序列化时不依赖
任何第三方库。model 仅作透传元数据（design §5.3），不决模型；tier 已出局
（integration_sl_draft v3.7 §11.1：tier 从家族全清零，ck 不再背负透传僵尸字段）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class GateMode(str, Enum):
    """闸模式（design §1.3）：服务端全局配置，请求无权控闸。

    - closed（默认）：拼装 → 直连 LLM → 返回。
    - auto（开闸）：拼装 → 生成/透传 context_id → 当场返 context，park 不调 LLM。
    """

    CLOSED = "closed"
    AUTO = "auto"


@dataclass
class SessionView:
    """ck 视角的会话只读视图（design §5.5 / 红线⑥只读）。

    ck 自持纯 chat 仅需三字段；sl 集成透传的 v0.5 路由字段本期不依赖。
    """

    permanent_system_prompt: str = ""
    loaded_docs: list[dict[str, str]] = field(default_factory=list)
    temp_history: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "permanent_system_prompt": self.permanent_system_prompt,
            "loaded_docs": self.loaded_docs,
            "temp_history": self.temp_history,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SessionView":
        return cls(
            permanent_system_prompt=data.get("permanent_system_prompt", ""),
            loaded_docs=data.get("loaded_docs", []),
            temp_history=data.get("temp_history", []),
        )


@dataclass
class ContextPatch:
    """pk 推理缝契约（design §5.5）：{phase_path, intent, context_id, ext}。

    组件形态（pk 填缝方）预留；本计划 serve 形态不实现该路径。
    tier 已出局（v3.7 §11.1）：字段集收敛为上述四元，不再含 tier。
    """

    phase_path: Optional[str] = None
    intent: Optional[str] = None
    context_id: Optional[str] = None
    ext: Optional[dict[str, Any]] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "phase_path": self.phase_path,
            "intent": self.intent,
            "context_id": self.context_id,
            "ext": self.ext,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ContextPatch":
        return cls(
            phase_path=data.get("phase_path"),
            intent=data.get("intent"),
            context_id=data.get("context_id"),
            ext=data.get("ext"),
        )


@dataclass
class InferenceResult:
    """推理收束产物（design §5.2）：{context_id, content, result_ref, ext, tool_calls}。

    tool_calls 为 G3 修复新增（concept §2.5/§6.6）：ck 返回层原样透传 LLM 的
    tool_calls，不再丢弃——分形全部走 ck，丢弃即阻断 sl 经 ck 调工具。
    默认 None（加法，不破坏旧调用方）；ck 自身不执行工具调度，循环归 sl。
    """

    context_id: str
    content: Any = None
    result_ref: Optional[str] = None
    ext: Optional[dict[str, Any]] = None
    tool_calls: Optional[list] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "context_id": self.context_id,
            "content": self.content,
            "result_ref": self.result_ref,
            "ext": self.ext,
            "tool_calls": self.tool_calls,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "InferenceResult":
        return cls(
            context_id=data["context_id"],
            content=data.get("content"),
            result_ref=data.get("result_ref"),
            ext=data.get("ext"),
            tool_calls=data.get("tool_calls"),
        )


@dataclass
class AssembledContext:
    """拼装内核产出（design §5.5）：messages 列表 + 区域索引（供闸 get 抽 content 视图）。"""

    messages: list[dict[str, Any]] = field(default_factory=list)
    # 区域索引：区域名 -> 在 messages 中的下标列表（供闸 get 抽取）
    region_index: dict[str, list[int]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "messages": self.messages,
            "region_index": self.region_index,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AssembledContext":
        return cls(
            messages=data.get("messages", []),
            region_index=data.get("region_index", {}),
        )


@dataclass
class CustomContext:
    """闸 get/set 的 content 视图字典（design §3.3）。

    按区域+次序组织的纯 content 字典；每条不带 role，role 留在 Session 原文。
    区域英文 key：permanent / temp / data_prefix / strategy 等。
    """

    regions: dict[str, dict[str, Any]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"regions": self.regions}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CustomContext":
        return cls(regions=data.get("regions", {}))

    # 便捷区域访问器
    @property
    def permanent(self) -> dict[str, Any]:
        return self.regions.get("permanent", {})

    @property
    def temp(self) -> dict[str, Any]:
        return self.regions.get("temp", {})

    @property
    def data_prefix(self) -> dict[str, Any]:
        return self.regions.get("data_prefix", {})

    @property
    def strategy(self) -> dict[str, Any]:
        return self.regions.get("strategy", {})
