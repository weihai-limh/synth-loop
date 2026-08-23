"""数据面下行（_a P4.3）——相位产物（规划/path/结果）存储与获取

与 packets（上行注入）对称：packets 喂上下文，artifacts 取产物。
- 产物 TTL 默认 24h（config.yaml artifacts.ttl_seconds），过期惰性清理
- chat 响应 content 只含人读摘要；完整产物经 artifact_ref 获取
"""

import json
import logging
import time
from typing import Any, Optional

from app.database import get_shared_db

logger = logging.getLogger(__name__)

DEFAULT_TTL = 24 * 3600  # 24h


async def save_artifact(artifact_id: str, pipeline_id: str = "",
                        kind: str = "", phase_index: Optional[str] = None,
                        content: Optional[Any] = None, summary: str = "",
                        ttl: Optional[int] = None) -> dict:
    """保存产物（plan/path/result/summary）。

    _c 放宽：artifact_id 唯一必填；pipeline_id/kind 可空；phase_index 支持 str
    （存 phase_path 树路径如 "0-1"，写入 phase_index_txt 列）；content 支持 str 或 dict。
    """
    from ..config import get_config
    config = get_config()
    ttl = ttl or config.get("artifacts", {}).get("ttl_seconds", DEFAULT_TTL)
    expires_at = int(time.time()) + ttl

    # content 支持 str/dict/None → JSON 序列化（str 会包引号，get_artifact json.loads 还原）
    db = await get_shared_db()
    await db.execute(
        """INSERT OR REPLACE INTO artifacts
           (artifact_id, pipeline_id, kind, phase_index_txt, content, summary, expires_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (artifact_id, pipeline_id, kind, phase_index,
         json.dumps(content, ensure_ascii=False) if content is not None else None,
         summary, expires_at),
    )
    await db.commit()
    return {"artifact_id": artifact_id, "kind": kind, "phase_index": phase_index}


async def get_artifact(artifact_id: str) -> Optional[dict]:
    """获取产物（过期惰性清理）"""
    db = await get_shared_db()
    cursor = await db.execute(
        "SELECT * FROM artifacts WHERE artifact_id = ?", (artifact_id,))
    row = await cursor.fetchone()
    if not row:
        return None
    if row["expires_at"] and row["expires_at"] < int(time.time()):
        await db.execute("DELETE FROM artifacts WHERE artifact_id = ?", (artifact_id,))
        await db.commit()
        return None
    result = dict(row)
    try:
        result["content"] = json.loads(result["content"]) if result["content"] else {}
    except Exception:
        result["content"] = {}
    return result


async def list_pipeline_artifacts(pipeline_id: str) -> list[dict]:
    """列出管道全部产物（时间线）"""
    db = await get_shared_db()
    cursor = await db.execute(
        """SELECT artifact_id, pipeline_id, kind, phase_index, summary, created_at
           FROM artifacts WHERE pipeline_id = ? AND (expires_at IS NULL OR expires_at >= ?)
           ORDER BY created_at""",
        (pipeline_id, int(time.time())),
    )
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]
