"""
Admin 路由 - v0_1_1: 用户管理 + strata-match 联动 + 可观测性
"""

import json
import logging
from pathlib import Path
from typing import Any, Optional

import httpx
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import HTMLResponse, FileResponse

from ..config import get_section, SRC_DIR
from ..database import create_user, delete_user, get_user, list_users, update_user
from ..services.analysis import Analysis
from ..services.job_store import get_job_store

logger = logging.getLogger(__name__)

router = APIRouter(tags=["admin"])

PUBLIC_DIR = SRC_DIR / "public"


# ========== 监听 API ==========

@router.post("/admin/listeners", summary="创建监听 Job")
async def create_listener(payload: dict):
    """创建监听 Job"""
    from uuid import uuid4
    session_id = payload.get("session_id", str(uuid4()))
    job_id = f"listener-{session_id}-{hash(str(payload)) & 0xFFFF:04x}"
    store = get_job_store()
    job = await store.create(job_id=job_id, job_type="listener", session_id=session_id, config=payload)
    return {"id": job.id, "job_type": job.job_type, "status": job.status}


@router.get("/admin/listeners", summary="查询监听 Job")
async def list_listeners(session_id: str = Query(None)):
    """查询监听 Job 列表"""
    store = get_job_store()
    if session_id:
        jobs = await store.list_by_session(session_id)
    else:
        jobs = await store.list_by_type("listener")
    return [{"id": j.id, "status": j.status, "session_id": j.session_id} for j in jobs]


@router.delete("/admin/listeners/{listener_id}", summary="删除监听 Job")
async def delete_listener(listener_id: str):
    store = get_job_store()
    success = await store.delete(listener_id)
    if not success:
        raise HTTPException(status_code=404, detail=f"Listener not found: {listener_id}")
    return {"status": "deleted"}


# ========== 管理面板 ==========

@router.get("/admin", response_class=HTMLResponse, summary="管理面板首页")
async def admin_hub():
    """v0_1_1: 统一管理导航"""
    return HTMLResponse(content="""<!DOCTYPE html>
<html lang="zh">
<head><meta charset="UTF-8"><title>synth-loop 管理面板</title>
<style>
body{font-family:system-ui,sans-serif;max-width:700px;margin:60px auto;padding:0 20px;background:#0d1117;color:#c9d1d9}
h1{color:#58a6ff;text-align:center;margin-bottom:40px}
.cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:16px}
.card{background:#161b22;border:1px solid #21262d;border-radius:8px;padding:20px 16px;text-decoration:none;color:#c9d1d9;transition:border-color .2s}
.card:hover{border-color:#58a6ff}
.card h3{margin:0 0 8px;color:#58a6ff;font-size:16px}
.card p{margin:0;font-size:13px;color:#8b949e}
.note{text-align:center;margin-top:40px;color:#484f58;font-size:12px}
</style></head>
<body>
<h1>synth-loop 管理面板</h1>
<div class="cards">
<a class="card" href="/admin/users/panel"><h3>用户管理</h3><p>创建/启用/禁用/删除用户</p></a>
<a class="card" href="/admin/sessions"><h3>会话管理</h3><p>查看活跃会话列表</p></a>
<a class="card" href="/admin/tasks"><h3>任务管理</h3><p>查看/取消异步任务</p></a>
<a class="card" href="/admin/jobs"><h3>Job 管理</h3><p>查看/管理监 Job</p></a>
<a class="card" href="/admin/analysis"><h3>分析报告</h3><p>事件分析报告</p></a>
<a class="card" href="/docs"><h3>API 文档</h3><p>Swagger UI</p></a>
</div>
<p class="note">synth-loop v0_1_1</p>
</body></html>""")


@router.get("/admin/sessions", response_class=HTMLResponse, summary="会话管理面板")
async def sessions_panel():
    path = PUBLIC_DIR / "sessions.html"
    if path.exists():
        return HTMLResponse(content=path.read_text(encoding="utf-8"))
    return HTMLResponse(content="<h1>Gateway Sessions</h1><p>面板加载中...</p>")


@router.get("/admin/tasks", response_class=HTMLResponse, summary="任务链管理面板")
async def tasks_panel():
    path = PUBLIC_DIR / "tasks.html"
    if path.exists():
        return HTMLResponse(content=path.read_text(encoding="utf-8"))
    return HTMLResponse(content="<h1>Task Chain Monitor</h1><p>面板加载中...</p>")


@router.get("/admin/jobs", response_class=HTMLResponse, summary="Job 管理面板")
async def jobs_panel():
    path = PUBLIC_DIR / "jobs.html"
    if path.exists():
        return HTMLResponse(content=path.read_text(encoding="utf-8"))
    return HTMLResponse(content="<h1>Job Manager</h1><p>面板加载中...</p>")


# ═══════════════════════════════════════════════════════════
# v0_1_1 Phase 3: 用户管理 + strata-match 联动注册
# ═══════════════════════════════════════════════════════════

STRATA_MATCH_USER_URL = "/api/v1/users"


async def _register_to_strata_match(sl_user_id: str) -> bool:
    """将 synth-loop 用户 `sl-xxx` 注册到 strata-match 为 `sm-xxx`"""
    sm_user_id = "sm-" + sl_user_id[3:]  # sl-{uuid} → sm-{uuid}
    sm_config = get_section("strata_match")
    sm_url = sm_config.get("url", "http://localhost:13156")
    timeout = sm_config.get("timeout", 5)

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(
                f"{sm_url}{STRATA_MATCH_USER_URL}",
                json={"id": sm_user_id},
            )
            if resp.status_code in (200, 201, 409):
                logger.info(f"strata-match user registered: {sm_user_id}")
                return True
            else:
                logger.warning(f"strata-match registration returned {resp.status_code}: {resp.text}")
                return False
    except Exception as e:
        logger.warning(f"strata-match registration failed (degraded): {e}")
        return False


@router.get("/admin/users", summary="用户列表")
async def users_list() -> list[dict[str, Any]]:
    """列出所有用户"""
    users = await list_users()
    return [{"id": u["id"], "enabled": bool(u["enabled"]), "display_name": u.get("display_name", ""),
             "created_at": u.get("created_at"), "updated_at": u.get("updated_at")} for u in users]


@router.post("/admin/users", summary="创建用户")
async def users_create(payload: dict[str, Any]):
    """创建用户（sl-{uuid}），联动注册到 strata-match"""
    user_id = payload.get("id", "")
    if not user_id.startswith("sl-"):
        raise HTTPException(status_code=400, detail="User ID must start with 'sl-'")

    display_name = payload.get("display_name", "")

    try:
        user = await create_user(user_id, display_name=display_name)
    except Exception as e:
        raise HTTPException(status_code=409, detail=f"User creation failed: {e}")

    # 联动注册到 strata-match（降级：失败不影响 synth-loop 侧创建）
    sm_ok = await _register_to_strata_match(user_id)

    return {
        "id": user["id"],
        "enabled": bool(user["enabled"]),
        "display_name": user.get("display_name", ""),
        "strata_match_registered": sm_ok,
    }


@router.put("/admin/users/{user_id}/disable", summary="禁用用户")
async def users_disable(user_id: str):
    """禁用用户"""
    user = await get_user(user_id)
    if not user:
        raise HTTPException(status_code=404, detail=f"User not found: {user_id}")
    await update_user(user_id, enabled=False)
    return {"id": user_id, "enabled": False}


@router.put("/admin/users/{user_id}/enable", summary="启用用户")
async def users_enable(user_id: str):
    """启用用户"""
    user = await get_user(user_id)
    if not user:
        raise HTTPException(status_code=404, detail=f"User not found: {user_id}")
    await update_user(user_id, enabled=True)
    return {"id": user_id, "enabled": True}


@router.delete("/admin/users/{user_id}", summary="删除用户")
async def users_delete(user_id: str):
    """删除用户"""
    success = await delete_user(user_id)
    if not success:
        raise HTTPException(status_code=404, detail=f"User not found: {user_id}")
    return {"status": "deleted", "id": user_id}


@router.get("/admin/users/panel", response_class=HTMLResponse, summary="用户管理面板")
async def users_panel():
    """用户管理 HTML 页面"""
    path = PUBLIC_DIR / "users.html"
    if path.exists():
        return HTMLResponse(content=path.read_text(encoding="utf-8"))
    return HTMLResponse(content="""<!DOCTYPE html>
<html lang="zh">
<head><meta charset="UTF-8"><title>synth-loop — 用户管理</title>
<style>
body{font-family:system-ui,sans-serif;max-width:900px;margin:40px auto;padding:0 20px;background:#0d1117;color:#c9d1d9}
h1{color:#58a6ff}
table{width:100%;border-collapse:collapse;margin:20px 0}
th,td{padding:10px 12px;text-align:left;border-bottom:1px solid #21262d}
th{background:#161b22;color:#8b949e}
tr:hover{background:#161b22}
input,button{padding:8px 12px;border:1px solid #30363d;border-radius:6px;background:#161b22;color:#c9d1d9;margin:4px}
button{background:#238636;color:#fff;border:none;cursor:pointer}
button.danger{background:#da3633}
button.warn{background:#d29922;color:#000}
input:focus{outline:none;border-color:#58a6ff}
.status{display:inline-block;padding:2px 8px;border-radius:4px;font-size:12px}
.status.active{background:#23863622;color:#3fb950}
.status.disabled{background:#da363322;color:#f85149}
</style></head>
<body>
<h1>用户管理</h1>
<div>
  <input id="newUserId" placeholder="sl-{uuid}" style="width:250px">
  <input id="newUserName" placeholder="显示名称" style="width:200px">
  <button onclick="createUser()">创建用户</button>
</div>
<table><thead><tr><th>ID</th><th>显示名</th><th>状态</th><th>创建时间</th><th>操作</th></tr></thead>
<tbody id="userTableBody"></tbody></table>
<script>
const BASE = '/admin/users';
async function loadUsers(){const r=await fetch(BASE);const d=await r.json();let h='';d.forEach(u=>{h+=`<tr>
<td>${u.id}</td><td>${u.display_name||'-'}</td>
<td><span class="status ${u.enabled?'active':'disabled'}">${u.enabled?'启用':'禁用'}</span></td>
<td>${u.created_at||'-'}</td>
<td>${u.enabled?`<button class="warn" onclick="toggleUser('${u.id}',false)">禁用</button>`:`<button onclick="toggleUser('${u.id}',true)">启用</button>`}
<button class="danger" onclick="delUser('${u.id}')">删除</button></td></tr>`});document.getElementById('userTableBody').innerHTML=h}
async function createUser(){const id=document.getElementById('newUserId').value;const dn=document.getElementById('newUserName').value;
if(!id.startsWith('sl-')){alert('ID 需以 sl- 开头');return}
await fetch(BASE,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id,display_name:dn})});loadUsers()}
async function toggleUser(id,enable){await fetch(`${BASE}/${id}/${enable?'enable':'disable'}`,{method:'PUT'});loadUsers()}
async function delUser(id){if(!confirm(`删除用户 ${id}?`))return;await fetch(`${BASE}/${id}`,{method:'DELETE'});loadUsers()}
loadUsers()
</script></body></html>""")


# ========== 分析 API ==========

@router.get("/admin/analysis", summary="事件分析报告")
async def analysis_report(session_id: str = Query(None)):
    """生成分析报告"""
    config = get_section("monitoring")
    raw_path = config.get("events_path", "data/events.jsonl")
    events_path = str(SRC_DIR / raw_path)
    analyzer = Analysis(events_path)
    events = analyzer.load_events(session_id)
    return analyzer.report(events)
