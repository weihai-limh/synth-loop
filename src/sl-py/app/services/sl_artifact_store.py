"""_c: 链路 C 相位产物桥接——sl 数据面实现 pk `ArtifactStore` 端口，落到 sl SQLite artifact_dataplane。

pk 引擎按 async 调 `artifact_store`（`await self.artifact_store.store(...)`），桥接实现必须 async 签名。
artifact_id = pk 的 ref（art_{pid}_{kind}_{phase_path}），唯一必填；其他列可空。

对齐 pk `InMemoryArtifactStore` 完整端口：store / fetch / transfer / fetch_external。
⚠️ media_type 语义：pk 产物 data 可能是 str（plan_summary/summary，media_type="text"）
或 dict（path/result，media_type="application/json"）。
⚠️ fetch 返回结构需对齐 pk 期望（含 `data` 键）——否则 pk `_fetch_best_context` 的 `art.get("data")` 拿不到。
"""

import logging
import re
import time
from typing import Any, Optional

import httpx

from ..services.artifact_dataplane import get_artifact, save_artifact

logger = logging.getLogger(__name__)

# http/https URL 判定（对齐 pk InMemoryArtifactStore._is_http_url）
_URL_RE = re.compile(r"^https?://", re.IGNORECASE)


def _is_http_url(payload: Any) -> bool:
    if not isinstance(payload, str):
        return False
    return bool(_URL_RE.match(payload.strip()))


def _new_ref(pipeline_id: str) -> str:
    return f"{pipeline_id}_{int(time.time() * 1000)}"


def _parse_ref(ref: str) -> tuple[Optional[str], Optional[str]]:
    """解析 pk ref：`art_{pid}_{kind}_{phase_path}` → (kind, phase_path)。

    - art_{pid}_plan → (plan, None)
    - art_{pid}_path_{phase_path} / _result_ / _summary_ → (kind, phase_path)
    """
    parts = ref.split("_")
    if len(parts) < 3:
        return None, None
    # parts = ["art", pid, kind, ...phase_path]
    pid = parts[1]
    kind = parts[2]
    phase_path = "_".join(parts[3:]) or None
    return kind, phase_path


class SlArtifactStore:
    """sl 数据面桥接：实现 pk `ArtifactStore` 端口，落到 sl SQLite artifact_dataplane。"""

    def __init__(self, allow_passthrough: bool = False):
        self.allow_passthrough = allow_passthrough

    async def store(self, pipeline_id: str, ref: str, data: Any,
                    media_type: str = "text") -> str:
        kind, phase_path = _parse_ref(ref)
        # summary 仅对 str 文本产物设置（dict 产物 summary 空，避免 SQLite 绑 dict 报错）
        summary = data if (media_type == "text" and isinstance(data, str)) else ""
        await save_artifact(
            artifact_id=ref,          # 唯一必填 = pk 的 ref
            pipeline_id=pipeline_id,
            kind=kind or "",
            phase_index=phase_path,   # phase_index 存 phase_path 树路径
            content=data,             # str 或 dict 均可（save_artifact content 放宽）
            summary=summary,
        )
        return f"/v1/artifacts/{ref}"  # 返回 sl 对外 URL

    async def fetch(self, ref: str) -> Optional[dict]:
        """取回产物。⚠️ 对齐 pk 期望结构：pk `_fetch_best_context` 用 `art.get("data")`。

        sl `get_artifact` 返回表字段 dict（含 content，无 data）——映射为
        `{pipeline_id, ref, data, media_type, at}`（对齐 pk InMemoryArtifactStore.fetch）。
        """
        art = await get_artifact(ref)
        if art is None:
            return None
        content = art.get("content")
        return {
            "pipeline_id": art.get("pipeline_id"),
            "ref": ref,
            "data": content,          # 原始内容（str/dict），pk 上下文切片用
            "media_type": "text" if isinstance(content, str) else "application/json",
            "at": art.get("created_at"),
        }

    async def fetch_external(self, url: str) -> Optional[str]:
        """拉取远端内容（真实 http 拉取，失败返回 None）。"""
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                return resp.text
        except Exception:
            logger.warning(f"fetch_external failed: {url}")
            return None

    async def transfer(self, pipeline_id: str, payload: Any,
                       media_type: str = "text") -> dict:
        """透传/拉取转存分流（对齐 pk InMemoryArtifactStore.transfer 完整语义）。

        返回：`{url, passthrough: bool, degraded: bool}`。
        """
        # 1) 透传：已是 http/https URL 且透传开关开 → 不落盘直转远端
        if _is_http_url(payload) and self.allow_passthrough:
            return {"url": payload.strip(), "passthrough": True, "degraded": False}
        # 2) 拉取转存：是 URL 但透传关 → 尝试拉取转存；失败降级直用远端 URL
        if _is_http_url(payload):
            content = await self.fetch_external(payload.strip())
            if content is not None:
                ref = _new_ref(pipeline_id)
                url = await self.store(pipeline_id, ref, content, media_type)
                return {"url": url, "passthrough": False, "degraded": False}
            return {"url": payload.strip(), "passthrough": True, "degraded": True,
                    "_transfer_degraded": True}
        # 3) 纯内容 → 直接转存
        ref = _new_ref(pipeline_id)
        url = await self.store(pipeline_id, ref, payload, media_type)
        return {"url": url, "passthrough": False, "degraded": False}
