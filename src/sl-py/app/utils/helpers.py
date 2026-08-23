"""工具函数模块"""

from typing import Any


def is_multimodal_content(content: Any) -> bool:
    """检查 content 是否为多模态格式（数组）"""
    return isinstance(content, list)


def get_text_from_content(content: Any) -> str:
    """
    从 content 中提取纯文本

    如果 content 是字符串，直接返回
    如果 content 是数组（多模态），提取 type=text 的内容拼接
    """
    if isinstance(content, str):
        return content

    if isinstance(content, list):
        texts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                texts.append(item.get("text", ""))
        return " ".join(texts)

    return str(content)


def truncate_string(s: str, max_length: int = 100) -> str:
    """截断字符串"""
    if len(s) <= max_length:
        return s
    return s[:max_length] + "..."
