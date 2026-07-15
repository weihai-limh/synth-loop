"""unload_document_from_context 工具实现"""

from typing import Any

from ..models.session import Session

# 工具定义
UNLOAD_DOCUMENT_DEFINITION = {
    "type": "function",
    "function": {
        "name": "unload_document_from_context",
        "description": "从永久上下文中卸载指定文档。",
        "parameters": {
            "type": "object",
            "properties": {
                "doc_id": {
                    "type": "string",
                    "description": "要卸载的文档ID，由 load_document_to_context 返回。",
                }
            },
            "required": ["doc_id"],
        },
    },
}


async def handle_unload_document(
    session: Session, args: dict[str, Any]
) -> dict[str, Any]:
    """
    处理 unload_document_from_context 工具调用

    Args:
        session: 当前会话
        args: 工具参数，包含 doc_id 字段

    Returns:
        执行结果
    """
    doc_id = args.get("doc_id", "")

    if not doc_id:
        return {"status": "error", "message": "doc_id 参数不能为空"}

    # 过滤掉指定文档
    original_count = len(session.loaded_docs)
    session.loaded_docs = [d for d in session.loaded_docs if d["doc_id"] != doc_id]

    if len(session.loaded_docs) == original_count:
        return {"status": "not_found", "doc_id": doc_id}

    session.snapshot_dirty = True
    return {"status": "unloaded", "doc_id": doc_id}
