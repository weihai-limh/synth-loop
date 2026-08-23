"""NoOp 数据面（adapters/noop_data_plane.py）——形态①产物面占位（dev-plan §2 / design §6.3）。

形态①纯 chat 无前序产物，NoOp 实现满足 DataPlane 端口：
- store / transfer 静默（返回 None / 空 dict）
- fetch 恒返回空 dict（无产物可拉）
"""

from __future__ import annotations

from typing import Any

from ..ports import DataPlane


class NoOpDataPlane(DataPlane):
    """形态①占位数据面；行为对齐 sl artifact_dataplane 的"无产物"语义。"""

    def store(self, pipeline_id: str, ref: str, data: Any) -> Any:
        return None

    def fetch(self, ref: str) -> dict[str, Any]:
        return {}

    def transfer(self, pipeline_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return {}
