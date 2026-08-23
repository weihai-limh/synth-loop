"""闸配置（core/gate_config.py）——可配置开闸 + 粒度旋钮（design §1.3/§4.4 / dev-plan §5）。

服务端全局配置（design §1.3）：请求无权控闸。运行时可经 /context-conf/ 切换
gate_mode。配置仅持有 GateMode，不做请求级覆盖。

自 2026-08-23 起新增 `context_mode`（拼装策略）维度，与 `gate_mode`（关/开闸）
正交：gate_mode 决定是否 park，context_mode 决定上下文怎么来。
- context_mode = "layered"（默认）：六层拼装（对齐 sl 定制拼装）。
- context_mode = "passthrough"：通用态，普通请求 messages 全量映射为
  {"context": {次序: 内容}}，供闸 set 定向覆写；与六层解耦。
"""

from __future__ import annotations

from typing import Any

from ..core.models import GateMode

# 合法 context_mode 闭集（协议闭集纪律，红线⑦）
_VALID_CONTEXT_MODES = ("layered", "passthrough")


class GateConfig:
    """服务端全局闸配置：gate_mode（关/开闸）+ context_mode（拼装策略）。"""

    def __init__(
        self,
        gate_mode: str | GateMode = "closed",
        context_mode: str = "layered",
    ) -> None:
        self._mode = gate_mode if isinstance(gate_mode, GateMode) else GateMode(gate_mode)
        self._context_mode = context_mode
        self._validate_context_mode(context_mode)

    @property
    def gate_mode(self) -> GateMode:
        return self._mode

    @property
    def context_mode(self) -> str:
        return self._context_mode

    @staticmethod
    def _validate_context_mode(mode: str) -> None:
        if mode not in _VALID_CONTEXT_MODES:
            raise ValueError(f"invalid context_mode: {mode}")

    def set_gate_mode(self, mode: str | GateMode) -> GateMode:
        """运行时切换闸模式（/context-conf/ 端点调用）。"""
        self._mode = mode if isinstance(mode, GateMode) else GateMode(mode)
        return self._mode

    def set_context_mode(self, mode: str) -> str:
        """运行时切换拼装策略（/context-conf/ 端点调用）。

        与 gate_mode 正交：只影响拼装策略，不影响关/开闸。
        """
        self._validate_context_mode(mode)
        self._context_mode = mode
        return self._context_mode

    def to_dict(self) -> dict[str, Any]:
        return {
            "gate_mode": self._mode.value,
            "context_mode": self._context_mode,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "GateConfig":
        return cls(
            gate_mode=data.get("gate_mode", "closed"),
            context_mode=data.get("context_mode", "layered"),
        )
