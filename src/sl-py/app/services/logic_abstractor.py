"""
LogicAbstractor - Phase 3: GW-P2 Dispatch
LLM 判定 subtype（code_generation/document_writing/...），输出给 strata-match。

v0_1_2_d (B3): 关键词词表外置到 complexity_rules.yaml 的 subtypes 段（真源），
启动期加载；兜底 general_qa 仍为 hardcode（design G2 明确）。
"""
import logging
import json
import re
from pathlib import Path
from typing import Optional

import yaml

logger = logging.getLogger(__name__)


def _load_subtype_keywords() -> dict[str, list[str]]:
    """从 complexity_rules.yaml 的 subtypes 段加载词表（真源）"""
    rules_path = Path(__file__).parent.parent.parent / "complexity_rules.yaml"
    with open(rules_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    patterns: dict[str, list[str]] = {}
    for item in data.get("subtypes", []) or []:
        name = item.get("name")
        kws = item.get("keywords", [])
        if name:
            patterns[name] = kws
    return patterns


# 逻辑类型 → 关键词模式（加载自 complexity_rules.yaml subtypes 段真源）
SUBTYPE_KEYWORDS: dict[str, list[str]] = _load_subtype_keywords()


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
            for kw in keywords:
                if re.search(kw, msg):
                    logger.info(f"LogicAbstractor: {subtype} matched by '{kw}'")
                    return subtype
        return "general_qa"
