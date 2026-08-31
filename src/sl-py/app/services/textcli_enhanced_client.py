"""强化客户端（Enhanced TextCli Client）——tc 消费链路执行面（_a P2.2）

替代现状三套自建实现（textcli_client / async_delegation 自建 POST / injection_pipeline 自建 POST）。
所有旅程（A 基础 / C 相位）的 tc 调用收敛到此客户端（P10）。

API（对齐 tc call.py）：
- call(prompt, alias=None) -> DirectiveResult  同步调用（SPEC 1.3.2 信封直读）
- discover(query=None, alias=None) -> list     指令发现（directives[]）
- poll(task_id, alias=None) -> dict            轮询异步任务（task.state 五态）
- wait(task_id, timeout=300, on_status=None)   阻塞等待（指数退避）

链路：前缀校验 → 凭 alias 查运行时表 → httpx POST → parse_envelope
"""

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

import httpx

from .runtime_endpoints import resolve_alias

logger = logging.getLogger(__name__)


@dataclass
class DirectiveResult:
    """SPEC 1.3.2 信封解析结果"""
    ok: bool
    data: dict = field(default_factory=dict)   # rst_data 直读
    rst_err: str = ""                           # 空=成功；非空=错误码（闭集）
    is_async: bool = False                      # status=="pending" + task_id
    task_id: Optional[str] = None               # is_async 时携带


def parse_envelope(resp_json: dict) -> DirectiveResult:
    """SPEC 1.3.2 信封解析（P15 修复：rst_data 直读，不再 .text 嵌套）"""
    rst_data = resp_json.get("rst_data", {})
    rst_err = resp_json.get("rst_err", "")
    if isinstance(rst_data, str):
        # 兼容旧嵌套兜底（不依赖）
        try:
            rst_data = json.loads(rst_data)
        except Exception:
            rst_data = {}
    is_async = (rst_data.get("status") == "pending") and bool(rst_data.get("task_id"))
    task_id = rst_data.get("task_id") if is_async else None
    return DirectiveResult(
        ok=(rst_err == ""),
        data=rst_data,
        rst_err=rst_err,
        is_async=is_async,
        task_id=task_id,
    )


class TextCLITaskError(Exception):
    def __init__(self, task_id: str, detail: Any = None):
        self.task_id = task_id
        self.detail = detail
        super().__init__(f"TextCLI task {task_id} failed: {detail}")


class EnhancedTextCliClient:
    """强化的 tc 改版 SDK——统一入口（P10 收敛）"""

    def __init__(self, default_timeout: int = 30):
        self.default_timeout = default_timeout

    # ── 内部：端点解析 + 请求 ────────────────────────────

    async def _resolve_and_post(self, prompt: str, alias: Optional[str]) -> httpx.Response:
        """凭 alias 查运行时表 → 依次尝试（同 alias rank 降级）→ POST"""
        from app.config import get_config
        config = get_config()
        default_alias = (config.get("runtime_endpoints") or {}).get("default_alias")

        candidates = await resolve_alias(alias, default_alias=default_alias)
        if not candidates:
            raise TextCLITaskError(task_id="?", detail=f"无可用运行时端点 (alias={alias})")

        last_err: Optional[Exception] = None
        for ep in candidates:
            try:
                headers = self._build_headers(ep)
                async with httpx.AsyncClient(timeout=self.default_timeout) as client:
                    resp = await client.post(ep["url"], json={"prompt": prompt}, headers=headers)
                    resp.raise_for_status()
                    return resp
            except httpx.HTTPStatusError as e:
                # 端点级错误：按错误码决定是否降级（参数错/鉴权败不降级）
                try:
                    body = e.response.json()
                    rst_err = body.get("rst_err", "")
                except Exception:
                    rst_err = ""
                if rst_err in {"INVALID_PARAMS", "ACCESS_DENIED", "SERVICE_DENIED"}:
                    raise  # 不降级（切换端点无意义）
                last_err = e
                logger.warning(f"Endpoint failed, trying next rank: {ep['alias']} - {rst_err or e}")
            except httpx.HTTPError as e:
                last_err = e
                logger.warning(f"Endpoint unreachable, trying next rank: {ep['alias']} - {e}")

        raise TextCLITaskError(task_id="?", detail=f"全部端点耗尽: {last_err}")

    @staticmethod
    def _build_headers(ep: dict) -> dict:
        """按 auth 三态注入 token"""
        headers = {"Content-Type": "application/json"}
        auth = ep.get("auth", "none")
        if auth in {"single", "dual"} and ep.get("service_token"):
            headers["Service-token"] = ep["service_token"]
        if auth == "dual" and ep.get("access_token"):
            headers["Authorization"] = f"Bearer {ep['access_token']}"
        return headers

    # ── 四函数 API ───────────────────────────────────────

    async def call(self, prompt: str, *, alias: Optional[str] = None) -> DirectiveResult:
        """同步调用：校验 AI: 前缀 → 解析端点/令牌 → POST → SPEC 1.3.2 信封解析"""
        if not prompt.startswith("AI:"):
            # 3.4：LLM 拼前缀，sl 校验透传（不二次拼装）
            prompt = f"AI:{prompt}"
        resp = await self._resolve_and_post(prompt, alias)
        return parse_envelope(resp.json())

    async def discover(self, query: Optional[str] = None, *, alias: Optional[str] = None) -> list[dict]:
        """指令发现：AI:text-cli;query[,json] → directives[]"""
        prompt = "AI:text-cli;query,json"
        if query and query != "json":
            prompt = f"AI:text-cli;query,{query}"
        result = await self.call(prompt, alias=alias)
        if not result.ok:
            logger.warning(f"discover failed: {result.rst_err}")
            return []
        return result.data.get("directives", [])

    async def poll(self, task_id: str, *, alias: Optional[str] = None) -> dict:
        """轮询异步任务：GET /text-cli/tasks/{id} → task.state 五态"""
        from app.config import get_config
        config = get_config()
        default_alias = (config.get("runtime_endpoints") or {}).get("default_alias")
        candidates = await resolve_alias(alias, default_alias=default_alias)
        if not candidates:
            raise TextCLITaskError(task_id=task_id, detail="无可用运行时端点")

        last_err: Optional[Exception] = None
        for ep in candidates:
            try:
                headers = self._build_headers(ep)
                base = ep["url"].rsplit("/cli", 1)[0]  # http://host/text-cli
                url = f"{base}/tasks/{task_id}"
                async with httpx.AsyncClient(timeout=self.default_timeout) as client:
                    resp = await client.get(url, headers=headers)
                    resp.raise_for_status()
                    body = resp.json()
                    task = body.get("task", {})
                    return task  # {task_id, state, result, progress}
            except httpx.HTTPError as e:
                last_err = e
                logger.warning(f"poll endpoint failed, trying next rank: {ep['alias']} - {e}")
        raise TextCLITaskError(task_id=task_id, detail=f"全部端点耗尽: {last_err}")

    async def wait(self, task_id: str, *, timeout: int = 300,
                   on_status: Optional[Callable[[dict], None]] = None,
                   alias: Optional[str] = None) -> dict:
        """阻塞等待：指数退避轮询直到 done/error/超时"""
        initial = 0.5
        maximum = 10.0
        elapsed = 0.0
        interval = initial
        while elapsed < timeout:
            task = await self.poll(task_id, alias=alias)
            state = task.get("state", "")
            if on_status:
                on_status(task)
            if state in {"done", "completed"}:
                return task
            if state == "error":
                raise TextCLITaskError(task_id=task_id, detail=task.get("result", {}))
            if state == "cancelled":
                raise TextCLITaskError(task_id=task_id, detail="task cancelled")
            await asyncio.sleep(interval)
            elapsed += interval
            interval = min(interval * 2, maximum)
        raise TimeoutError(f"TextCLI task {task_id} timed out after {timeout}s")


# 全局实例（单例工厂，对齐原 textcli_client）
_enhanced_client: Optional[EnhancedTextCliClient] = None


def get_enhanced_client() -> EnhancedTextCliClient:
    global _enhanced_client
    if _enhanced_client is None:
        _enhanced_client = EnhancedTextCliClient()
    return _enhanced_client
