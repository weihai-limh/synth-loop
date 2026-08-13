"""discover_textcli 工具：发现 text-cli 可用指令"""

import logging
import time
from typing import Optional

from ..services.textcli_client import get_textcli_client

logger = logging.getLogger(__name__)


class DiscoverCache:
    """指令发现缓存"""
    
    def __init__(self, ttl: int = 300):
        self.cache = {}
        self.ttl = ttl
    
    def get(self, key: str) -> Optional[str]:
        """获取缓存"""
        if key in self.cache:
            entry = self.cache[key]
            if time.time() - entry["time"] < self.ttl:
                logger.info(f"DiscoverCache cache hit: {key}")
                return entry["value"]
            else:
                del self.cache[key]
        return None
    
    def set(self, key: str, value: str):
        """设置缓存"""
        self.cache[key] = {
            "value": value,
            "time": time.time()
        }
        logger.info(f"DiscoverCache cache set: {key}")


# 全局缓存实例
discover_cache = DiscoverCache(ttl=300)


async def handle_discover_textcli(session, args: dict) -> dict:
    """处理 discover_textcli 工具调用"""
    query = args.get("query", "")
    format_type = args.get("format", "compact")
    
    logger.info(f"handle_discover_textcli: query={query}, format={format_type}")
    
    # 检查缓存
    cache_key = f"{query}:{format_type}"
    cached = discover_cache.get(cache_key)
    if cached:
        return {"status": "cached", "instructions": cached}
    
    # 调用 text-cli
    try:
        textcli_client = get_textcli_client()
        result = await textcli_client.discover(query)
        discover_cache.set(cache_key, result)
        return {"status": "success", "instructions": result}
    except Exception as e:
        logger.error(f"handle_discover_textcli failed: {e}")
        return {"status": "error", "message": str(e)}


# 工具定义
DISCOVER_TEXTCLI_DEFINITION = {
    "type": "function",
    "function": {
        "name": "discover_textcli",
        "description": "发现 text-cli 可用指令，支持关键词过滤",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "可选，关键词过滤"
                },
                "format": {
                    "type": "string",
                    "description": "可选，返回格式：compact | full | json"
                }
            }
        }
    }
}
