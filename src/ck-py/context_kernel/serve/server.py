"""serve 外挂：双形态 HTTP 服务层（serve/server.py）——对齐 pk 范式（design §2.3 / dev-plan §6）。

纯标准库 `ThreadingHTTPServer`（不引 FastAPI，零依赖纪律与 pk 一致）。把已落地的
`ContextKernel.run_openai` / `gate_get` / `gate_set` / `gate_mode` 包成独立可部署服务，
达成 pk 等价闭环（组件 + serve 外挂双形态）。

端点（与 `ContextKernel` 公共方法一一对应，不复制拼装/闸逻辑，红线⑦）：
  POST /v1/chat/completions   折叠态入口（closed 直推 / auto park）
  GET  /chatgate/{context_id} 取回 content 视图
  POST /chatgate/{context_id} 反向修正后推 LLM（unpark 一次性令牌）
  GET  /context-conf/         读服务端全局闸配置
  POST /context-conf/         改 gate_mode（请求无权控闸，仅服务端配置）
  GET  /health                {status, degraded_mode, gate_mode}
  GET  /schema                返回 CK_SCHEMA

形态一：`python -m context_kernel.serve.server [--port 8080]`
形态二：组件集成——`from context_kernel.serve.server import build_app` 复用 handler。
两形态共用 `core/context_kernel.py` 与 `__init__.py` 导出。
"""

from __future__ import annotations

import argparse
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from ..core.context_kernel import ContextKernel
from ..core.gate_config import GateConfig
from ..core.models import GateMode, SessionView
from ..ports import ContextSource, DataPlane, LlmProvider
from ..serve.session_store import SessionStore


class _StoreSource(ContextSource):
    """用 SessionStore 满足 ContextSource 只读契约（serve 层即上下文源）。"""

    def __init__(self, store: SessionStore) -> None:
        self._store = store

    def read_session(self, session_id: str) -> SessionView:
        # serve 外挂 demo 用进程内单会话视图；session_id 透传给内核追踪，
        # 视图内容来自 SessionStore（形态①纯 chat 单视图）。
        return self._store.read_view()


def make_kernel(
    llm_provider: LlmProvider,
    data_plane: DataPlane | None = None,
    store: SessionStore | None = None,
    primary_model: str = "ck-primary",  # E2：缺省模型（请求未带 model 时回落），非唯一模型
    fallback_model: str = "ck-fallback",
    gate_mode: str | GateMode = "closed",
    context_mode: str = "layered",
) -> ContextKernel:
    """构造独立部署用 ContextKernel（注入会话源 + 数据面占位）。"""
    store = store or SessionStore()
    source: ContextSource = _StoreSource(store)
    dp: DataPlane = data_plane or _NullDataPlane()
    return ContextKernel(
        source, dp, llm_provider, primary_model, fallback_model, gate_mode, context_mode
    )


class _NullDataPlane(DataPlane):
    """形态①纯 chat 无前序产物时的数据面占位（与 NoOpDataPlane 语义一致）。"""

    def store(self, packet_id: str, role: str, payload: dict[str, Any]) -> None:
        return None

    def fetch(self, ref: str) -> dict[str, Any]:
        return {}

    def transfer(self, packet_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return {}


CK_SCHEMA = {
    "service": "context-kernel",
    "messages_shape": "openai-chat",
    "request_contract": {
        "model": "str|null（透传至下游 LLM；缺省回落 primary_model，不决模型语义）",
        "stream": "bool|null（closed 路径透传；gate_set 恒非流，忽略）",
        "metadata.ext.service_name": "str|null（D1：服务标识，缺省 None 按实现默认回落）",
    },
    "envelope": {
        "closed": {
            "context_id": "str",
            "content": "str|null",
            "result_ref": "null",
            "tool_calls": "list|null（G3 透传：原样返回 LLM tool_calls，不丢弃）",
            "ext": {"model": "str", "usage": "object|null"},
        },
        "auto": {
            "context_id": "str",
            "context": "list[region]",
            "gate": "pending",
        },
    },
    "gate_protocol": {
        "park": "POST /v1/chat/completions (gate_mode=auto) -> {context_id, context, gate:pending}",
        "peek": "GET /chatgate/{context_id} -> {context_id, context}",
        "amend": "POST /chatgate/{context_id} (body=custom) -> InferenceResult; unpark 一次性",
    },
    "outputs": {
        "content": "str|null",
        "context_id": "str",
        "tool_calls": "list|null（G3 透传）",
    },
    "directives": ["gate_mode", "degraded_mode"],
}


class CKHandler(BaseHTTPRequestHandler):
    """HTTP 端点 handler——只调 ContextKernel 公共方法，不复制逻辑。"""

    protocol_version = "HTTP/1.1"
    kernel: ContextKernel
    store: SessionStore

    # --- 工具 ---
    def _send(self, code: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length == 0:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def log_message(self, *args: Any) -> None:  # 静默默认访问日志
        return

    # --- 路由 ---
    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0].rstrip("/")
        if path in ("", "/"):
            return self._send(200, {"service": "context-kernel", "status": "ok"})
        if path == "/health":
            return self._send(200, {
                "status": "ok",
                "degraded_mode": False,
                "gate_mode": self.kernel.gate_mode.value,
            })
        if path == "/schema":
            return self._send(200, CK_SCHEMA)
        if path == "/context-conf":
            return self._send(200, self.kernel.gate_config.to_dict())
        if path.startswith("/chatgate/"):
            cid = path[len("/chatgate/"):]
            if not cid:
                return self._send(400, {"error": "missing context_id"})
            resp = self.kernel.gate_get(cid)
            if "error" in resp:
                return self._send(404, resp)
            return self._send(200, resp)
        return self._send(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0].rstrip("/")
        if path == "/v1/chat/completions":
            body = self._read_json()
            # 折叠态入口：closed 直推 / auto park；请求不控闸，用服务端 gate_mode
            result = self.kernel.run_openai(body)
            from ..core.models import InferenceResult
            if isinstance(result, dict) and result.get("gate") == "pending":
                return self._send(200, result)  # auto 不推 LLM，返 park 视图
            # closed：InferenceResult -> OpenAI 兼容 envelope
            assert isinstance(result, InferenceResult)
            env = {
                "context_id": result.context_id,
                "content": result.content,
                "result_ref": result.result_ref,
                "ext": result.ext,
            }
            if result.tool_calls is not None:  # E5：G3 透传，None 时省略键（零破坏旧调用方）
                env["tool_calls"] = result.tool_calls
            return self._send(200, env)
        if path == "/context-conf":
            body = self._read_json()
            if "gate_mode" in body:
                mode = body.get("gate_mode")
                if mode is None:
                    return self._send(400, {"error": "missing gate_mode"})
                try:
                    self.kernel.set_gate_mode(mode)
                except ValueError:
                    return self._send(400, {"error": f"invalid gate_mode: {mode}"})
            if "context_mode" in body:
                cmode = body.get("context_mode")
                if cmode is None:
                    return self._send(400, {"error": "missing context_mode"})
                try:
                    self.kernel.gate_config.set_context_mode(cmode)
                except ValueError:
                    return self._send(400, {"error": f"invalid context_mode: {cmode}"})
            return self._send(200, self.kernel.gate_config.to_dict())
        if path.startswith("/chatgate/"):
            cid = path[len("/chatgate/"):]
            if not cid:
                return self._send(400, {"error": "missing context_id"})
            body = self._read_json()
            custom = body.get("context") or body.get("custom") or body
            try:
                res = self.kernel.gate_set(cid, custom)
            except KeyError:
                return self._send(404, {"error": "unknown context_id"})
            env = {
                "context_id": res.context_id,
                "content": res.content,
                "result_ref": res.result_ref,
                "ext": res.ext,
            }
            if res.tool_calls is not None:  # E5：G3 透传，None 时省略键（零破坏旧调用方）
                env["tool_calls"] = res.tool_calls
            return self._send(200, env)
        return self._send(404, {"error": "not found"})


def build_app(
    llm_provider: LlmProvider,
    data_plane: DataPlane | None = None,
    store: SessionStore | None = None,
    primary_model: str = "ck-primary",  # E2：缺省模型（请求未带 model 时回落）
    fallback_model: str = "ck-fallback",
    gate_mode: str | GateMode = "closed",
    context_mode: str = "layered",
    port: int = 8080,
) -> ThreadingHTTPServer:
    """形态二：组件集成——返回可复用 HTTP server（handler 直接 import 内核）。"""
    kernel = make_kernel(
        llm_provider, data_plane, store, primary_model, fallback_model, gate_mode, context_mode
    )
    CKHandler.kernel = kernel  # type: ignore[attr-defined]
    CKHandler.store = store or SessionStore()  # type: ignore[attr-defined]
    return ThreadingHTTPServer(("0.0.0.0", port), CKHandler)


def main() -> None:
    parser = argparse.ArgumentParser(description="ck serve 外挂（双形态 HTTP 服务层）")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--gate-mode", default="closed", choices=["closed", "auto"])
    parser.add_argument("--model", default="ck-primary")
    parser.add_argument("--context-mode", default="layered", choices=["layered", "passthrough"])
    args = parser.parse_args()

    # 真实部署应注入真实 LlmProvider；此处默认 Mock（测试/演示）。
    from ..adapters.mock_llm import MockLlmProvider
    server = build_app(
        MockLlmProvider("<mock reply>"),
        port=args.port,
        primary_model=args.model,
        gate_mode=args.gate_mode,
        context_mode=args.context_mode,
    )
    print(f"ck serve on :{args.port}  gate_mode={args.gate_mode}  context_mode={args.context_mode}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == "__main__":
    main()
