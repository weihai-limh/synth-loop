# ========== synth-loop mock server（sl-web-chat 联调用） ==========
# 目标：1:1 照 docs/api_zh.md 的 response schema 实现 synth-loop 关键端点，
#       内置足够预置数据，使 sl-web-chat 能在浏览器完整演练：
#         - 永久区 longdata 增/删/列
#         - 临时区 packets 提交
#         - 相位闸多轮推进（plan → path → approval → completed）
#         - ck 推理闸 park / amend / 放行
#         - artifact 取回（6.5.3 视图）
# 注意：本 mock 仅用于前端正确性验证；真实联调差异 = 后端债项（非前端 bug）。
import os
import uuid
import json
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, Request, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles

app = FastAPI(title="synth-loop mock")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_credentials=True,
    allow_methods=["*"], allow_headers=["*"],
)

# ---------- 内存状态 ----------
SESSIONS: Dict[str, str] = {}                       # header session -> synth session id
LONGDATA: Dict[str, List[Dict[str, Any]]] = {}      # session_id -> [longdata]
PACKETS: List[Dict[str, Any]] = []                  # packet 记录
PIPELINES: Dict[str, Dict[str, Any]] = {}           # pipeline_id -> state
CHATEGATES: Dict[str, Dict[str, Any]] = {}          # context_id -> {context, amended, released}
ARTIFACTS: Dict[str, Dict[str, Any]] = {}           # artifact_id -> artifact

# ---------- 预置数据 ----------
def seed():
    # 永久区：预置 2 条（doc + memory），绑在演示会话 s_demo
    LONGDATA["s_demo"] = [
        {"id": "ld_seed_doc", "session_id": "s_demo", "type": "doc",
         "content": "智能家居市场调研背景：2025 年国内智能家居渗透率达 35%。", "created_at": 1756000000},
        {"id": "ld_seed_mem", "session_id": "s_demo", "type": "memory",
         "content": "<user-memory>用户偏好简洁的图表化报告。</user-memory>", "created_at": 1756000100},
    ]
    # artifacts：相位 plan / path / result
    ARTIFACTS["art_p1_plan"] = {
        "artifact_id": "art_p1_plan", "pipeline_id": "p1", "phase_index": 0,
        "kind": "plan", "content": "相位规划摘要：3 个相位（市场分析 / 竞品调研 / 报告撰写）。",
        "data": {"phases": ["市场分析", "竞品调研", "报告撰写"]},
        "created_at": "2026-08-14T03:00:00",
    }
    ARTIFACTS["art_p1_path_0"] = {
        "artifact_id": "art_p1_path_0", "pipeline_id": "p1", "phase_index": 0,
        "kind": "path", "content": "相位 1/3「市场分析」路径信封。",
        "data": {"id": "local", "name": "市场分析",
                 "steps": [{"action": "execute", "description": "分析目标市场"}]},
        "created_at": "2026-08-14T03:01:00",
    }
    ARTIFACTS["art_p1_result_1"] = {
        "artifact_id": "art_p1_result_1", "pipeline_id": "p1", "phase_index": 1,
        "kind": "result", "content": "人读摘要：竞品调研完成。",
        "data": {"output": "竞品 A/B/C 对比..."},
        "created_at": "2026-08-14T03:02:00",
    }

seed()

# ---------- 工具 ----------
def get_session(request: Request) -> str:
    hdr = request.headers.get("x-synthloop-session-id")
    if hdr:
        SESSIONS[hdr] = hdr
        return hdr
    sid = "s_demo"   # mock 默认会话，便于预置数据可见
    return sid

def chat_resp(content: str, extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    resp = {
        "id": "chatcmpl-mock-" + uuid.uuid4().hex[:8],
        "object": "chat.completion",
        "model": "mock-model",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": content},
                     "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0},
    }
    if extra:
        resp.update(extra)
    return resp

# ---------- 主 chat 端点 ----------
@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    body = await request.json()
    messages = body.get("messages", [])
    last = messages[-1]["content"] if messages else ""
    synth = body.get("synth_pipeline")            # 回传 {id, action}
    session = get_session(request)

    # 1) ck 推理闸：若已 amend 过该 context，放行出结果
    #    触发条件：用户消息含 <gate> 标签 → 第一次返回 pending
    if SESSIONS.get(session + ":gate") == "amended_ok":
        # 已 amend，放行出结果
        del SESSIONS[session + ":gate"]
        return chat_resp("推理闸已放行：基于修正后的上下文，结论为 X。")
    if "<gate>" in last and not SESSIONS.get(session + ":gate"):
        cid = "cg_" + uuid.uuid4().hex[:8]
        CHATEGATES[cid] = {"context": {"region_index": 2, "paused_reason": "ck 推理闸 park"},
                           "amended": False, "released": False}
        SESSIONS[session + ":gate"] = cid
        return chat_resp(
            "上下文已提交推理闸（gate=pending），请在卡片中编辑后 amend。",
            {"gate": "pending", "context_id": cid, "context": CHATEGATES[cid]["context"]},
        )

    # 2) 相位闸：首轮触发
    if ("<tc-phase>" in last or "<tc-phase-chain>" in last) and not synth:
        # pipeline_id 按 session 限定，避免全局单例 'p1' 跨会话共享导致状态互相污染
        # （如一个会话完成 pop 后，另一会话回传 confirm 得到 400 unknown pipeline_id）
        pid = "p1_" + session
        PIPELINES[pid] = {"id": pid, "step": "awaiting_plan_confirm",
                          "phase_index": 0, "phase_total": 3, "artifact_ref": "art_p1_plan"}
        return chat_resp(
            "相位规划如下（共 3 个相位）：\n1. 市场分析\n2. 竞品调研\n3. 报告撰写\n\n请确认（回传 action=confirm）...",
            {"synth_pipeline": PIPELINES[pid]},
        )

    # 3) 相位闸：回传推进
    if synth and synth.get("id"):
        pid = synth["id"]
        st = PIPELINES.get(pid)
        if not st:
            raise HTTPException(400, "unknown pipeline_id")
        action = synth.get("action")
        if action == "abort":
            PIPELINES.pop(pid, None)
            return chat_resp("相位流程已中止。")
        if action == "reject":
            return chat_resp(
                "已驳回（意见：" + str(synth.get("opinion", "")) + "），请重新确认当前步骤。",
                {"synth_pipeline": st},
            )
        # confirm / regenerate：步进
        if st["step"] == "awaiting_plan_confirm":
            st.update({"step": "awaiting_path_confirm", "phase_index": 0,
                       "artifact_ref": "art_p1_path_0"})
            return chat_resp(
                '相位 1/3「市场分析」的 path 如下：\n{"id": "local", "name": "市场分析", "steps": [{"action": "execute", "description": "分析目标市场"}]}\n\n确认执行（confirm）/ 驳回修改（reject + 意见）/ 中止（abort）。',
                {"synth_pipeline": st},
            )
        if st["step"] == "awaiting_path_confirm":
            st.update({"step": "awaiting_approval", "phase_index": 1,
                       "artifact_ref": "art_p1_result_1"})
            return chat_resp(
                "相位 1/3 执行完成，产物见 artifact。进入审批环节，请确认（confirm）/ 驳回（reject）/ 中止（abort）。",
                {"synth_pipeline": st},
            )
        if st["step"] == "awaiting_approval":
            st.update({"step": "completed", "phase_index": 2, "artifact_ref": "art_p1_result_1"})
            PIPELINES.pop(pid, None)
            return chat_resp(
                "全部相位完成，报告已生成。",
                {"synth_pipeline": {"id": pid, "step": "completed", "phase_index": 2, "phase_total": 3}},
            )

    # 4) 普通对话
    return chat_resp("（mock）收到：" + last[:80])

# ---------- 数据面：packets 临时区 ----------
@app.post("/v1/packets")
async def post_packet(request: Request):
    body = await request.json()
    if not body.get("type"):
        raise HTTPException(400, "packet type required")
    pid = "pkt_" + uuid.uuid4().hex[:16]
    PACKETS.append({"packet_id": pid, **body})
    return {"packet_id": pid}

# ---------- 数据面：longdata 永久区 ----------
@app.post("/v1/longdata")
async def post_longdata(request: Request):
    body = await request.json()
    session_id = body.get("session_id") or get_session(request)
    typ = body.get("type")
    content = body.get("content")
    if typ not in ("doc", "memory") or not content:
        raise HTTPException(400, "type must be doc/memory and content required")
    lid = "ld_" + uuid.uuid4().hex[:10]
    item = {"id": lid, "session_id": session_id, "type": typ,
            "content": content, "created_at": 1756000000}
    LONGDATA.setdefault(session_id, []).append(item)
    return {"id": lid}

@app.get("/v1/longdata")
async def get_longdata(session_id: str = Query(...)):
    items = LONGDATA.get(session_id, [])
    # mock 演示兜底：目标 session 无数据时返回预置的 s_demo 数据，让前端开屏即可见预置条目
    if not items and session_id != "s_demo":
        items = LONGDATA.get("s_demo", [])
    return {"session_id": session_id, "items": items}

@app.delete("/v1/longdata/{lid}")
async def del_longdata(lid: str, session_id: str = Query(...)):
    items = LONGDATA.get(session_id, [])
    for i, it in enumerate(items):
        if it["id"] == lid:
            items.pop(i)
            return {"deleted": True}
    return {"deleted": False}

# ---------- ck 推理闸干预端点 ----------
@app.get("/chatgate/{context_id}")
async def chatgate_peek(context_id: str):
    g = CHATEGATES.get(context_id)
    if not g:
        raise HTTPException(404, "context not found (mock)")
    return {"context_id": context_id, "context": g["context"], "amended": g["amended"]}

@app.post("/chatgate/{context_id}")
async def chatgate_amend(context_id: str, request: Request):
    g = CHATEGATES.get(context_id)
    if not g:
        raise HTTPException(404, "context not found (mock)")
    body = await request.json()
    patch = (body or {}).get("context", {})
    g["context"] = patch
    g["amended"] = True
    # 标记该会话已 amend（前端 amend 请求会带 x-synthloop-session-id 头）
    sid = request.headers.get("x-synthloop-session-id") or "s_demo"
    SESSIONS[sid + ":gate"] = "amended_ok"
    return {"context_id": context_id, "context": g["context"], "amended": True}

# ---------- artifacts 制品数据面 ----------
@app.get("/api/v1/artifacts/{artifact_id}")
async def get_artifact(artifact_id: str):
    a = ARTIFACTS.get(artifact_id)
    if not a:
        raise HTTPException(404, "artifact not found (mock)")
    return a

@app.get("/api/v1/artifacts")
async def list_artifacts(pipeline_id: str = Query(...)):
    items = [a for a in ARTIFACTS.values() if a.get("pipeline_id") == pipeline_id]
    items.sort(key=lambda x: x.get("phase_index", 0))
    return {"items": items}

# ---------- 健康检查 ----------
@app.get("/health")
async def health():
    return {"status": "ok", "mock": True}


# ---------- 同源静态托管 HTML ----------
# 用 http://127.0.0.1:13155/ 打开即可（同源 http，fetch 不被浏览器拦截）。
# 注意：不要直接双击用 file:// 打开 HTML —— file: origin 会被浏览器禁止向
# http://127.0.0.1 发起 fetch（报 "file: URLs are treated as unique security origins"），
# 导致 Add failed / 对话失败等伪错误。务必经本 mock server 同源访问。
_HTML_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# HTML 托管统一加 no-store：避免浏览器缓存旧版产物，联调时每次刷新都拿最新
async def _html_resp(name):
    return FileResponse(
        os.path.join(_HTML_DIR, name),
        headers={"Cache-Control": "no-store", "Pragma": "no-cache"},
    )


@app.get("/")
async def index():
    return await _html_resp("sl-web-chat.html")


@app.get("/sl-web-chat.html")
async def chat_html():
    return await _html_resp("sl-web-chat.html")


@app.get("/sl-web-chat_zh.html")
async def chat_html_zh():
    return await _html_resp("sl-web-chat_zh.html")


# 静态资源（src/ 下的 js/css 等，若后续拆分；目录不存在则跳过以免启动崩溃）
_src_dir = os.path.join(_HTML_DIR, "src")
if os.path.isdir(_src_dir):
    app.mount("/src", StaticFiles(directory=_src_dir, html=False), name="src")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=13155)
