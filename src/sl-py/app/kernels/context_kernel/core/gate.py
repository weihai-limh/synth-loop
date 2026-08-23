"""推理闸（core/gate.py）——auto 模式编排 + park 存储（design §3.3/§4.3/§5.4 / dev-plan §6）。

新机制（sl 无对应）：推理前观测 + 反向修正。
- park：context_id -> 拼装快照（AssembledContext + 原始请求上下文），瞬时、不入库、
  park 表随进程生命周期（design §5.4：context_id 瞬时不入库）。
- /chatgate/{context_id} GET：取回 content 视图（CustomContext，按区域+次序）。
- /chatgate/{context_id} POST：修正推 LLM，仅改 park 输入快照，绝不回调 append_turn（红线⑥）。
- auto 模式：拼装后当场返 {context_id, context, gate:"pending"}，不调 LLM（design §4.3）。
"""

from __future__ import annotations

from typing import Any, Optional
from uuid import uuid4

from ..core.models import AssembledContext, CustomContext, GateMode
from ..core.assembler import build_prompt


class GatePark:
    """park 存储：context_id -> 拼装快照（瞬时字典，进程级）。"""

    def __init__(self) -> None:
        self._park: dict[str, dict[str, Any]] = {}

    def park(
        self,
        assembled: AssembledContext,
        session_view: Any,
        client_system_messages: Optional[list[dict[str, Any]]] = None,
        override_system: Optional[str] = None,
        current_user_content: Optional[str] = None,
        session_id: Optional[str] = None,
        ext: Optional[dict[str, Any]] = None,
        model: Optional[str] = None,
    ) -> str:
        """park 一份拼装快照，返回新生成的 context_id。

        model：开闸路径无 LLM 决策，但记录 park 时上下文模型（G1 透传闭环——
        gate_set 修正推沿用该 model，使开闸修正推与首次模型一致）。
        """
        context_id = uuid4().hex
        self._park[context_id] = {
            "assembled": assembled,
            "session_view": session_view,
            "client_system_messages": client_system_messages,
            "override_system": override_system,
            "current_user_content": current_user_content,
            "session_id": session_id,
            "ext": ext or {},
            "model": model,
        }
        return context_id

    def get(self, context_id: str) -> Optional[dict[str, Any]]:
        return self._park.get(context_id)

    def update_assembled(self, context_id: str, assembled: AssembledContext) -> None:
        """闸 set：仅改 park 内的拼装输入快照（绝不回调 append_turn，红线⑥）。"""
        if context_id in self._park:
            self._park[context_id]["assembled"] = assembled

    def unpark(self, context_id: str) -> None:
        self._park.pop(context_id, None)


def extract_custom_context(assembled: AssembledContext) -> CustomContext:
    """从拼装结果抽取 content 视图（design §3.3）：按区域+次序，每条不带 role。

    region_index 已分区（session_id/permanent/loaded_docs/client_system/temp/current）。
    各区域按下标顺序组织为 {序号: content} 字典。
    """
    regions: dict[str, dict[str, Any]] = {}
    for region, idxs in assembled.region_index.items():
        ordered: dict[str, Any] = {}
        for i, idx in enumerate(idxs):
            ordered[str(i)] = assembled.messages[idx].get("content")
        regions[region] = ordered
    return CustomContext(regions=regions)


def reassemble_from_custom(
    base_assembled: AssembledContext,
    custom: CustomContext,
) -> AssembledContext:
    """闸 set 修正：用 CustomContext 覆盖各区域 content，重组 messages。

    仅替换 content，role 与区域结构保持不变（design §3.3：role 留在 Session 原文）。
    区域 key 与 base_assembled.region_index 对齐。
    """
    messages = [dict(m) for m in base_assembled.messages]
    for region, idxs in base_assembled.region_index.items():
        patch = custom.regions.get(region, {})
        for i, idx in enumerate(idxs):
            if str(i) in patch:
                messages[idx]["content"] = patch[str(i)]
    return AssembledContext(messages=messages, region_index=base_assembled.region_index)
