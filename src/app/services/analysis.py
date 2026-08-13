"""
Analysis - Phase 4: GW-P6 可观测性
读 events.jsonl，按维度生成分析报告。
"""

import json
import logging
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


class Analysis:
    """事件分析器"""

    def __init__(self, events_path: str = "./data/events.jsonl"):
        self.events_path = Path(events_path)

    def load_events(self, session_id: Optional[str] = None) -> list[dict]:
        """加载事件"""
        if not self.events_path.exists():
            return []
        events = []
        with open(self.events_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    evt = json.loads(line)
                    if session_id and evt.get("session_id") != session_id:
                        continue
                    events.append(evt)
                except json.JSONDecodeError:
                    continue
        return events

    def report(self, events: list[dict]) -> dict:
        """生成分析报告"""
        if not events:
            return {"message": "No event data"}

        types = Counter(e.get("type", "unknown") for e in events)
        sessions = Counter(e.get("session_id", "unknown") for e in events if e.get("session_id"))
        complexities = defaultdict(int)
        total_tokens = 0
        total_latency = 0.0

        for e in events:
            if e.get("type") == "dispatch":
                complexities[e.get("complexity", "unknown")] += 1
            if e.get("type") == "response":
                total_tokens += e.get("token_count", 0)
                total_latency += e.get("latency_ms", 0)

        return {
            "total_events": len(events),
            "event_types": dict(types),
            "session_count": len(sessions),
            "complexity_distribution": dict(complexities),
            "total_tokens": total_tokens,
            "avg_latency_ms": round(total_latency / max(len(events), 1), 1),
            "generated_at": datetime.utcnow().isoformat(),
        }
