"""
ComplexityClassifier - Phase 3: GW-P2 Dispatch (v0.5-hotfix-2)
规则仅覆盖两端极值（chat / task_chain），中间地带返回 "fractal" 走分形 Prompt。
规则唯一来源: complexity_rules.yaml。文件缺失 → 全部走分形。
"""
import logging
import yaml
import re
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class ComplexityRule:
    """单条复杂度规则"""
    def __init__(self, data: dict):
        self.name: str = data.get("name", "")
        self.level: str = data.get("level", "chat")  # chat | task_chain
        self.patterns: list[str] = data.get("patterns", [])
        self.enabled: bool = data.get("enabled", True)


class ComplexityClassifier:
    """复杂度分类器 — 规则唯一来源: complexity_rules.yaml"""

    def __init__(self, rules_path: Optional[str] = None):
        self._rules: list[ComplexityRule] = []
        if rules_path:
            self.load_rules(rules_path)
        if not self._rules:
            logger.warning("No complexity rules loaded, all requests will go to fractal dispatch")

    def load_rules(self, path: str):
        """从 complexity_rules.yaml 加载规则（replace, not append）"""
        p = Path(path)
        if not p.exists():
            logger.warning(f"complexity_rules.yaml not found: {path}, using fractal-only mode")
            return
        with open(p, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        loaded = data.get("rules", [])
        self._rules = [ComplexityRule(r) for r in loaded if r.get("enabled", True)]
        logger.info(f"Loaded {len(self._rules)} complexity rules from {path}")

    def classify(self, user_message: str) -> str:
        """
        规则匹配 → 返回 complexity 级别
        Returns: "chat" | "task_chain" | "fractal"
        """
        msg = user_message.lower()
        for rule in self._rules:
            if not rule.enabled:
                continue
            for pattern in rule.patterns:
                if re.search(pattern, msg):
                    logger.info(f"Complexity rule matched: {rule.name} -> {rule.level}")
                    return rule.level
        # 无规则匹配 → 走分形 Prompt
        return "fractal"
