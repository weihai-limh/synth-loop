"""strata-match 客户端，用于获取策略"""

import logging
import time
from typing import Optional

import httpx

logger = logging.getLogger(__name__)


class StrataMatchClient:
    """strata-match 客户端"""
    
    def __init__(self, url: str, timeout: int = 5, cache_ttl: int = 3600, mock: bool = False):
        self.url = url
        self.timeout = timeout
        self.cache_ttl = cache_ttl
        self.mock = mock
        self.client = httpx.AsyncClient(timeout=timeout)
        self.cache = {}
        logger.info(f"StrataMatchClient initialized: url={url}, mock={mock}")
    
    async def query(self, user_ask: str, types: str = None, subtypes: str = None) -> dict:
        """查询 strata-match（v0.1 支持 subtypes 过滤）"""
        logger.info(f"StrataMatchClient.query: user_ask={user_ask}, types={types}, subtypes={subtypes}")
        
        # Mock 模式
        if self.mock:
            return self._mock_query(user_ask)
        
        # 检查缓存
        cache_key = f"{user_ask}:{types}:{subtypes}"
        cached = self._get_cache(cache_key)
        if cached:
            logger.info(f"StrataMatchClient cache hit: {cache_key}")
            return cached
        
        # 调用服务
        try:
            payload = {"user_ask": user_ask}
            if types:
                payload["types"] = types
            if subtypes:
                payload["subtypes"] = subtypes
            
            response = await self.client.post(
                f"{self.url}/api/v1/query",
                json=payload
            )
            response.raise_for_status()
            result = response.json()
            
            # 缓存结果
            self._set_cache(cache_key, result)
            
            logger.info(f"StrataMatchClient.query succeeded: matched_skills={result.get('matched_skills_tags', [])}")
            return result
        except Exception as e:
            logger.error(f"StrataMatchClient.query failed: {e}")
            raise
    
    def _get_cache(self, key: str) -> Optional[dict]:
        """获取缓存"""
        if key in self.cache:
            entry = self.cache[key]
            if time.time() - entry["time"] < self.cache_ttl:
                return entry["value"]
            else:
                del self.cache[key]
        return None
    
    def _set_cache(self, key: str, value: dict):
        """设置缓存"""
        self.cache[key] = {
            "value": value,
            "time": time.time()
        }
    
    def _mock_query(self, user_ask: str) -> dict:
        """Mock 查询"""
        logger.info(f"StrataMatchClient._mock_query: user_ask={user_ask}")
        
        # 根据用户意图返回不同的 Prompt
        prompt = self._get_prompt_by_intent(user_ask)
        
        return {
            "primary_prompt": prompt,
            "candidates": [],
            "matched_tags": ["通用"],
            "user_ask": user_ask,
            "category": "role_play",
            "compose_info": None,
            "assets": []
        }
    
    def _get_prompt_by_intent(self, user_ask: str) -> str:
        """根据用户意图返回 Prompt"""
        user_ask_lower = user_ask.lower()
        
        # 数学计算相关
        if any(keyword in user_ask_lower for keyword in ["计算", "数学", "算", "面积", "体积", "公式"]):
            return "你是一个专业的数学计算助手。你擅长各种数学计算，包括基本运算、几何、代数、微积分等。请用清晰的步骤和公式来解答数学问题。"
        
        # 编程相关
        if any(keyword in user_ask_lower for keyword in ["代码", "编程", "python", "javascript", "函数", "变量"]):
            return "你是一个专业的编程助手。你擅长多种编程语言，能够帮助用户编写、调试和优化代码。请提供清晰的代码示例和解释。"
        
        # 写作相关
        if any(keyword in user_ask_lower for keyword in ["写", "文章", "邮件", "辞职信", "报告"]):
            return "你是一个专业的写作助手。你擅长各种文体的写作，包括文章、邮件、报告、简历等。请提供结构清晰、语言流畅的内容。"
        
        # 翻译相关
        if any(keyword in user_ask_lower for keyword in ["翻译", "translate", "英文", "中文"]):
            return "你是一个专业的翻译助手。你擅长中英文互译，能够准确传达原文意思，同时保持语言的自然流畅。"
        
        # 数据分析相关
        if any(keyword in user_ask_lower for keyword in ["数据", "分析", "统计", "图表"]):
            return "你是一个专业的数据分析师。你擅长数据处理、统计分析和数据可视化。请用清晰的图表和指标来展示分析结果。"
        
        # 默认 Prompt
        return "你是一个有帮助的AI助手。请用清晰、准确、友好的方式回答用户的问题。"
    
    async def close(self):
        """关闭客户端"""
        await self.client.aclose()


# 全局实例
_strata_match_client: Optional[StrataMatchClient] = None


def get_strata_match_client() -> StrataMatchClient:
    """获取 StrataMatchClient 单例"""
    global _strata_match_client
    if _strata_match_client is None:
        from ..config import get_section
        config = get_section("strata_match")
        _strata_match_client = StrataMatchClient(
            url=config.get("url", "http://localhost:13156"),
            timeout=config.get("timeout", 5),
            cache_ttl=config.get("cache_ttl", 3600),
            mock=config.get("mock", False)
        )
    return _strata_match_client
