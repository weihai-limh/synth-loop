// ========== sl-context.js ==========
// synth-loop 【数据面】通道（packets 临时区 + longdata 永久区）。
// 重要区分（5.5 纠偏）：
//   - 本文件是【数据面】：用户主动往系统喂"上下文原料"（doc/memory/传感器/网页…），
//     属于独立的常驻管理 UI，与闸流程无关。
//   - 【ck 推理闸上下文编辑】是另一回事：由 ck 闸（gate:"pending"）唤起，编辑被 park 的
//     context 后 amend（见 sl-gate.js 的 amendGateContext）。它不是数据面注入。
// 本文件只做数据链接：直接对接 synth-loop REST 契约，不含任何 UI。
// UI（数据面管理面板）留待 Phase 6.5（联调前专门处理）。
// 依赖（同 <script> 共享作用域）：runtimeConfig / getSynthSessionId

// ---------- 工具：由 chat baseUrl 推导 API 根 ----------
// runtimeConfig.baseUrl 形如 "http://127.0.0.1:13155/v1/chat/completions"
// 或 "/v1/chat/completions"（同源相对），截掉 "/chat/completions" 得 "/v1"
function slApiRoot() {
    const base = (runtimeConfig.baseUrl || '').trim();
    const marker = '/chat/completions';
    const idx = base.lastIndexOf(marker);
    return idx !== -1 ? base.slice(0, idx) : base;   // 无后缀则原样（兼容已填根地址）
}

// 服务根（不含 /v1 前缀）：用于 chatgate（根路径）/ artifacts（/api/v1 路径）等
// 不在 /v1 下的端点。slApiRoot() 返回 /v1，这里剥掉末尾 /v1 得服务根。
// 例：baseUrl=/v1/chat/completions → slApiRoot()=/v1 → slApiOrigin()='/'（同源相对）
//    baseUrl=http://host:13155/v1/chat/completions → slApiOrigin()='http://host:13155'
function slApiOrigin() {
    const root = slApiRoot().replace(/\/v1$/, '');
    return root || '/';
}

async function slApiFetch(path, options) {
    const url = slApiRoot() + path;
    const headers = { 'Content-Type': 'application/json', ...runtimeConfig.headers };
    // 与 sendToLLM 对齐：启用 synth-loop 且已有会话时带 session 头，保证数据面与会话一致
    if (runtimeConfig.enableSynthLoop && typeof getSynthSessionId === 'function' && getSynthSessionId()) {
        headers['x-synthloop-session-id'] = getSynthSessionId();
    }
    const res = await fetch(url, { ...options, headers });
    let data = null;
    try { data = await res.json(); } catch (e) { /* 空响应 */ }
    if (!res.ok) {
        const msg = (data && (data.error || data.detail)) || ('HTTP ' + res.status);
        throw new Error(typeof msg === 'string' ? msg : JSON.stringify(msg));
    }
    return data;
}

// ---------- packets 临时区 ----------
// 待注入当前会话的 packet id 列表（会话级，Clean 时清空）
let pendingPacketIds = [];

// POST /v1/packets  { source, type, payload, meta } → { packet_id }
async function submitPacket({ source = 'sl-web-chat', type, payload = {}, meta = {} } = {}) {
    if (!type) throw new Error('packet type required');
    // slApiRoot() 已含 /v1 前缀（由 baseUrl 截出），path 不再带 /v1，避免 /v1/v1 重复
    const data = await slApiFetch('/packets', {
        method: 'POST',
        body: JSON.stringify({ source, type, payload, meta })
    });
    if (data && data.packet_id) pendingPacketIds.push(data.packet_id);  // 自动入待注入队列
    return data.packet_id;
}

function getPendingPacketIds() { return pendingPacketIds.slice(); }
function clearPendingPacketIds() { pendingPacketIds = []; }

// ---------- longdata 永久区 ----------
// POST /v1/longdata  { session_id, type, content } → result
async function addLongdata({ type, content, session_id = getSynthSessionId() } = {}) {
    if (!session_id) throw new Error('session_id required (先发起一次对话以建立会话)');
    if (!type || !content) throw new Error('type & content required');
    return await slApiFetch('/longdata', {
        method: 'POST',
        body: JSON.stringify({ session_id, type, content })
    });
}

// GET /v1/longdata?session_id= → { items: [...] }
async function listLongdata(session_id = getSynthSessionId()) {
    if (!session_id) throw new Error('session_id required');
    return await slApiFetch('/longdata?session_id=' + encodeURIComponent(session_id), {
        method: 'GET'
    });
}

// DELETE /v1/longdata/{id}?session_id= → result（后端按 id+session 双重校验）
async function deleteLongdata({ id, session_id = getSynthSessionId() } = {}) {
    if (!session_id || !id) throw new Error('id & session_id required');
    return await slApiFetch('/longdata/' + encodeURIComponent(id) + '?session_id=' + encodeURIComponent(session_id), {
        method: 'DELETE'
    });
}

if (typeof module !== 'undefined' && module.exports) {
    module.exports = {
        slApiRoot, slApiOrigin, submitPacket, addLongdata, listLongdata, deleteLongdata,
        getPendingPacketIds, clearPendingPacketIds
    };
}
