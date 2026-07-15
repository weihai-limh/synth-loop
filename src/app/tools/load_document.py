"""load_document_to_context 工具实现"""

from typing import Any

import httpx

from ..config import get_section
from ..models.session import Session

# 工具定义
LOAD_DOCUMENT_DEFINITION = {
    "type": "function",
    "function": {
        "name": "load_document_to_context",
        "description": "加载一个文档到永久上下文区，作为回答依据。支持 md 和 json 文件。",
        "parameters": {
            "type": "object",
            "properties": {
                "doc_name": {
                    "type": "string",
                    "description": "文档名称（无需路径）",
                },
                "chapter": {
                    "type": "string",
                    "description": "指定章节或键名（可选），默认返回全文。",
                },
            },
            "required": ["doc_name"],
        },
    },
}


async def handle_load_document(
    session: Session, args: dict[str, Any]
) -> dict[str, Any]:
    """
    处理 load_document_to_context 工具调用

    Args:
        session: 当前会话
        args: 工具参数，包含 doc_name 和可选的 chapter 字段

    Returns:
        执行结果
    """
    doc_name = args.get("doc_name", "")
    chapter = args.get("chapter", None)

    # 获取配置
    doc_config = get_section("document_service")
    document_service_url = doc_config.get("url", "http://localhost:8001")

    try:
        # 调用文档服务
        async with httpx.AsyncClient(timeout=10) as client:
            payload: dict[str, Any] = {"name": doc_name}
            if chapter:
                payload["chapter"] = chapter

            response = await client.post(
                f"{document_service_url}/load",
                json=payload,
            )
            response.raise_for_status()
            data = response.json()

        doc_id = data.get("doc_id", "")
        content = data.get("content", "")

        if not doc_id or not content:
            return {"status": "error", "message": "文档服务返回数据不完整"}

        # 检查是否已加载
        for doc in session.loaded_docs:
            if doc["doc_id"] == doc_id:
                return {"status": "already_loaded", "doc_id": doc_id}

        # 追加到永久区
        session.loaded_docs.append({"doc_id": doc_id, "content": content})
        session.snapshot_dirty = True

        return {"status": "loaded", "doc_id": doc_id}

    except httpx.HTTPStatusError as e:
        return {"status": "error", "message": f"文档服务请求失败: {e.response.status_code}"}
    except Exception as e:
        return {"status": "error", "message": str(e)}
