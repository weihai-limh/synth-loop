"""Mock strata-match 服务，用于开发阶段"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)


class MockStrataMatch:
    """Mock strata-match 服务"""
    
    def __init__(self):
        logger.info("MockStrataMatch 初始化")
    
    async def query(self, user_ask: str, types: str = None) -> dict:
        """模拟 strata-match 查询"""
        logger.info(f"MockStrataMatch.query: user_ask={user_ask}, types={types}")
        
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


# 全局实例
_mock_strata_match: Optional[MockStrataMatch] = None


def get_mock_strata_match() -> MockStrataMatch:
    """获取 MockStrataMatch 单例"""
    global _mock_strata_match
    if _mock_strata_match is None:
        _mock_strata_match = MockStrataMatch()
    return _mock_strata_match
