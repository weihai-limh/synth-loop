"""
LogicAbstractor - Phase 3: GW-P2 Dispatch
LLM 判定 subtype（code_generation/document_writing/...），输出给 strata-match。
"""
import logging
import json
from typing import Optional

logger = logging.getLogger(__name__)

SUBTYPE_KEYWORDS = {
    "document_writing": ["写", "报告", "计划书", "文档", "文章", "方案", "策划", "撰写", "编写", "起草"],
    "code_generation": ["代码", "编程", "开发", "函数", "类", "算法", "python", "java", "javascript", "写一个"],
    "code_review": ["审查", "review", "优化.*代码", "重构", "code review"],
    "creative_writing": ["故事", "小说", "诗歌", "创意", "情节", "角色"],
    "data_analysis": ["分析.*数据", "统计", "图表", "趋势", "报表", "指标"],
    "design_generation": ["设计", "UI", "界面", "海报", "logo", "插图"],
    "translation": ["翻译", "translate", "译成", "转换.*语言"],
}


class LogicAbstractor:
    """逻辑抽象器：规则匹配判定 subtype"""

    def abstract(self, user_message: str) -> str:
        """
        基于关键词判定用户意图的 subtype

        Returns:
            subtype 字符串：document_writing / code_generation / ...
        """
        msg = user_message.lower()
        for subtype, keywords in SUBTYPE_KEYWORDS.items():
            import re
            for kw in keywords:
                if re.search(kw, msg):
                    logger.info(f"LogicAbstractor: {subtype} matched by '{kw}'")
                    return subtype
        return "general_qa"
