"""拼装内核（core/assembler.py）——六层拼装 + 区域索引（design §3.1 / dev-plan §1）。

对齐母体 synth-loop context_router.build_messages 实测六层顺序（P1 任务 1.1）：
  1. Session-ID（永久区标识）
  2. 永久区系统提示（可 override_system 覆盖）
  3. 已加载文档（loaded_docs）
  4. 客户端系统消息（client_system_messages 合并）
  5. 临时会话窗口（temp_history deque）
  6. 当前用户内容（current_user_content）

本文件零外部依赖，仅落拼装骨架（P1 任务 1.2~1.3：决策路由/复杂度/三态
延后到 P4）。区域索引供闸 get 抽取 content 视图（design §3.3）。
"""

from __future__ import annotations

from typing import Any, Optional

from ..core.models import AssembledContext, SessionView


def build_prompt(
    session_view: SessionView,
    client_system_messages: Optional[list[dict[str, Any]]] = None,
    override_system: Optional[str] = None,
    current_user_content: Optional[str] = None,
    session_id: Optional[str] = None,
    routing: Any = None,
) -> AssembledContext:
    """六层拼装，返回 AssembledContext + region_index。

    参数说明（对齐 sl build_messages 实测）：
    - session_view: 会话只读视图（永久区+临时区）。
    - client_system_messages: 客户端额外 system（层4），默认空。
    - override_system: 覆盖永久区系统提示（层2），对应 sl override_system。
    - current_user_content: 当前用户消息文本（层6）。
    - routing: 决策路由结果占位（P4 复杂度/路由落此），本 Phase 透传不影响拼装。
    """
    messages: list[dict[str, Any]] = []
    region_index: dict[str, list[int]] = {}

    def append(region: str, role: str, content: Any) -> None:
        idx = len(messages)
        messages.append({"role": role, "content": content})
        region_index.setdefault(region, []).append(idx)

    # 层1：Session-ID（永久区标识，system 承载，对齐 sl build_messages 实测第46行）
    # ck 不持有 session_id 写权（design §4.5 写权属 serve），此处仅消费透传值。
    if session_id is not None:
        append("session_id", "system", f"Session-ID: {session_id}")

    # 层2：永久区系统提示（可被 override_system 覆盖）
    sys_prompt = override_system if override_system is not None else session_view.permanent_system_prompt
    if sys_prompt:
        append("permanent", "system", sys_prompt)

    # 层3：已加载文档
    for doc in session_view.loaded_docs:
        doc_id = doc.get("doc_id", doc.get("id", ""))
        content = doc.get("content", "")
        append("loaded_docs", "system", f"[{doc_id}]\n{content}")

    # 层4：客户端系统消息
    for msg in (client_system_messages or []):
        append("client_system", "system", msg.get("content", ""))

    # 层5：临时会话窗口（temp_history 原序）
    for turn in session_view.temp_history:
        role = turn.get("role", "user")
        content = turn.get("content", "")
        append("temp", role, content)

    # 层6：当前用户内容
    if current_user_content is not None:
        append("current", "user", current_user_content)

    return AssembledContext(messages=messages, region_index=region_index)


def build_passthrough(
    messages: Optional[list[dict[str, Any]]] = None,
) -> AssembledContext:
    """通用态拼装：普通 OpenAI 请求 messages 原样透传（design §新增 context_mode）。

    不做六层重排、不丢弃任何消息；全量 messages 按原序映射为单个 region
    "context" 的 {次序: 内容}，供闸 set 定向覆写 content（role 保留原文）。

    - region 固定为 "context"（单区域），与六层多区域解耦。
    - role 保留在消息原文；覆写仅改 content（对齐 reassemble_from_custom 语义）。
    """
    src = messages or []
    out_messages = [dict(m) for m in src]
    region_index: dict[str, list[int]] = {"context": list(range(len(out_messages)))}
    return AssembledContext(messages=out_messages, region_index=region_index)
