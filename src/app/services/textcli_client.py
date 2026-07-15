"""text-cli 客户端，用于调用 text-cli 服务"""

import logging
from typing import Optional

import httpx

logger = logging.getLogger(__name__)


class TextCliClient:
    """text-cli 客户端"""
    
    def __init__(self, endpoints: list, default_endpoint: str, timeout: int = 10):
        self.endpoints = endpoints
        self.default_endpoint = default_endpoint
        self.timeout = timeout
        self.client = httpx.AsyncClient(timeout=timeout)
        logger.info(f"TextCliClient 初始化: default_endpoint={default_endpoint}")
    
    async def call(self, prompt: str, endpoint: str = None) -> dict:
        """调用 text-cli 指令"""
        url = endpoint or self.default_endpoint
        logger.info(f"TextCliClient.call: url={url}, prompt={prompt}")
        
        try:
            response = await self.client.post(
                url,
                json={"prompt": prompt}
            )
            response.raise_for_status()
            result = response.json()
            logger.info(f"TextCliClient.call 成功: {result}")
            return result
        except Exception as e:
            logger.error(f"TextCliClient.call 失败: {e}")
            raise
    
    async def discover(self, query: str = None, endpoint: str = None) -> str:
        """发现可用指令"""
        prompt = "AI:text-cli;query,compact"
        if query:
            prompt = f"AI:text-cli;query,{query}"
        
        logger.info(f"TextCliClient.discover: query={query}")
        
        try:
            result = await self.call(prompt, endpoint)
            text = result.get("rst_data", {}).get("text", "")
            logger.info(f"TextCliClient.discover 成功: {text[:100]}...")
            return text
        except Exception as e:
            logger.error(f"TextCliClient.discover 失败: {e}")
            raise
    
    async def close(self):
        """关闭客户端"""
        await self.client.aclose()


# 全局实例
_textcli_client: Optional[TextCliClient] = None


def get_textcli_client() -> TextCliClient:
    """获取 TextCliClient 单例"""
    global _textcli_client
    if _textcli_client is None:
        from app.config import get_section
        config = get_section("textcli")
        _textcli_client = TextCliClient(
            endpoints=config.get("endpoints", []),
            default_endpoint=config.get("default_endpoint", "http://10.168.1.151/text-cli/cli"),
            timeout=config.get("timeout", 10)
        )
    return _textcli_client
