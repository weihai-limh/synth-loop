// ========== sl-gate.js ==========
// synth-loop 闸数据链接层（ck 推理闸 + pk 三闸）。
// 重要区分（5.5 纠偏）：
//   - 【ck 推理闸上下文编辑】在此：响应 gate:"pending" 时推理上下文被 park，
//     用户编辑 context 后 amend（fetchGateContext / amendGateContext）→ 这是闸流程内的一步，由 ck 闸唤起。
//   - 【数据面】（packets/longdata）不在此文件，见 sl-context.js —— 两者正交，不要混淆。
// 本阶段只做数据链接：解析 chat 响应字段 + 构造回传，不含任何 UI。
// UI（闸卡片 / 上下文编辑子面板 / 计划编辑子面板）留待 Phase 6.5。
// 依赖（同 <script> 共享作用域）：runtimeConfig / slApiRoot（来自 sl-context.js）
//
// 后端契约（已核实 src/sl-py/app/routers/chat.py）：
//   ck 推理闸：响应顶层 { gate:"pending", context_id, context }（chat.py:546-567）
//             → 干预端点 GET/POST /chatgate/{context_id}（gate.py 注释声明，但 P3 阶段未实现，联调会 404）
//             注意：此处的"上下文编辑"= 编辑被 park 的推理上下文，绝非数据面注入。
//   pk 三闸：请求体带 synth_pipeline:{id, action}（chat.py:301）→ 响应带 synth_pipeline:{id,step,...}（:319-329）
//             → 前端原样回传，无独立端点

// ---------- 闸事件队列（会话级，供 UI 消费） ----------
// 放在先加载模块，避免 sl-gate.js 的 renderPendingGateCards 调用时尚未定义。
let pendingGateEvents = [];

function getPendingGateEvents() { return pendingGateEvents.slice(); }
function clearPendingGateEvents() { pendingGateEvents = []; }
function pushGateEvent(evt) { if (evt && evt.kind) pendingGateEvents.push(evt); }

// ---------- 解析 chat 响应：分流两类闸 ----------
// 返回 { kind:'ck'|'pk'|null, ... }，供 Phase 6.5 UI 渲染
function parseGateFromResponse(resp) {
    if (!resp || typeof resp !== 'object') return { kind: null };
    // pk 相位闸：响应带 synth_pipeline 字段
    // 但 step==='completed' 是相位终态（mock 已完成并 pop pipeline），
    // 不应再渲染带确认/驳回按钮的闸卡片，否则会触发多余的 confirm → 400 unknown pipeline_id。
    if (resp.synth_pipeline && resp.synth_pipeline.id && resp.synth_pipeline.step !== 'completed') {
        return { kind: 'pk', pipeline: resp.synth_pipeline };
    }
    // ck 推理闸：响应带 gate:"pending"
    if (resp.gate === 'pending' && resp.context_id) {
        return { kind: 'ck', context_id: resp.context_id, context: resp.context || {} };
    }
    return { kind: null };
}

// ---------- ck 推理闸：干预（端点后端 P3 未实现，数据层照写，联调登记附录 C） ----------
async function fetchGateContext(contextId) {
    // chatgate 在服务根路径（非 /v1 下），用 slApiOrigin() 而非 slApiRoot()
    const url = slApiOrigin().replace(/\/$/, '') + '/chatgate/' + encodeURIComponent(contextId);
    const res = await fetch(url, { headers: { ...runtimeConfig.headers } });
    if (!res.ok) throw new Error('GET /chatgate/' + contextId + ' → HTTP ' + res.status + '（后端 P3 未实现，见附录 C）');
    return await res.json();
}

async function amendGateContext(contextId, patch) {
    const url = slApiOrigin().replace(/\/$/, '') + '/chatgate/' + encodeURIComponent(contextId);
    const res = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...runtimeConfig.headers },
        body: JSON.stringify(patch || {})
    });
    if (!res.ok) throw new Error('POST /chatgate/' + contextId + ' → HTTP ' + res.status + '（后端 P3 未实现，见附录 C）');
    return await res.json();
}

// ---------- pk 三闸：回传（注入下一轮 chat 请求体，无独立端点） ----------
let pendingSynthPipelineReturn = null;   // { id, action }

// 构造下一轮 chat 请求要带的 synth_pipeline 回传字段
function takePendingSynthPipelineReturn() {
    const r = pendingSynthPipelineReturn;
    pendingSynthPipelineReturn = null;   // 消费即清空（每次确认/驳回只回传一次）
    return r;
}

// UI 在 Phase 6.5 调用：把用户动作转为回传（confirm/reject/regenerate/abort/...）
function queueSynthPipelineReturn(pipelineId, action, opinion) {
    pendingSynthPipelineReturn = { id: pipelineId, action: action, ...(opinion ? { opinion } : {}) };
}

// peek：是否有待回传（供 sl-chat 提交拦截放行，不消费）
function hasPendingSynthPipelineReturn() {
    return !!pendingSynthPipelineReturn;
}

// ---------- Phase 5：计划编辑数据层（相位 plan/path 文本 + artifact 取回） ----------
// 说明：本阶段只做数据链接，UI（结构化展示/确认面板）留 Phase 6.5。
// 依赖 slApiRoot（来自 sl-context.js）/ runtimeConfig。

// 从 synth_pipeline 安全提取 plan/path 文本（字段名由 Phase 7 校准，此处容错）
function extractPlanFromPipeline(pipeline) {
    if (!pipeline || typeof pipeline !== 'object') return null;
    // 优先常见字段，回退到整对象 JSON（UI 层再决定如何呈现）
    const cand = pipeline.plan || pipeline.plan_text || pipeline.phase_goal ||
                 pipeline.path || pipeline.path_text;
    if (typeof cand === 'string' && cand.trim()) return cand;
    if (cand && typeof cand === 'object') return JSON.stringify(cand, null, 2);
    return null;
}

// artifact 取回（端点已核实 api_zh.md:751/767 为 /api/v1/artifacts/{id} 与 /api/v1/artifacts?pipeline_id=）
async function fetchArtifact(artifactId) {
    // artifacts 在 /api/v1 下（非 /v1 的 chat 根），用 slApiOrigin()
    const url = slApiOrigin().replace(/\/$/, '') + '/api/v1/artifacts/' + encodeURIComponent(artifactId);
    const res = await fetch(url, { headers: { ...runtimeConfig.headers } });
    if (!res.ok) throw new Error('GET /api/v1/artifacts/' + artifactId + ' → HTTP ' + res.status);
    return await res.json();
}

async function listPipelineArtifacts(pipelineId) {
    const url = slApiOrigin().replace(/\/$/, '') + '/api/v1/artifacts?pipeline_id=' + encodeURIComponent(pipelineId);
    const res = await fetch(url, { headers: { ...runtimeConfig.headers } });
    if (!res.ok) throw new Error('GET /api/v1/artifacts?pipeline_id=' + pipelineId + ' → HTTP ' + res.status);
    return await res.json();
}

if (typeof module !== 'undefined' && module.exports) {
    module.exports = {
        parseGateFromResponse, fetchGateContext, amendGateContext,
        takePendingSynthPipelineReturn, queueSynthPipelineReturn,
        extractPlanFromPipeline, fetchArtifact, listPipelineArtifacts,
        renderPendingGateCards, renderGateCard
    };
}

// ========== 以下为 Phase 6.5.2 UI 层：闸管理卡片 ==========
// 消费 getPendingGateEvents()（sl-chat.js 推送），渲染两类卡片并接回传。
// 纯 OpenAI 模式（!enableSynthLoop）不渲染。
// 依赖（同 <script> 共享作用域）：getPendingGateEvents / clearPendingGateEvents（sl-chat.js）、
//   runtimeConfig、slApiRoot、t（sl-integrate.js）、messagesContainer（sl-chat.js）

// 入口：在每轮助手回答收尾后调用。队列为空则无操作。
function renderPendingGateCards() {
    if (!runtimeConfig.enableSynthLoop) return;
    const events = getPendingGateEvents();
    if (!events || !events.length) return;
    events.forEach((evt) => renderGateCard(evt));
    clearPendingGateEvents();   // 渲染即消费，避免重复
}

function gateStepTitle(kind, pipeline) {
    if (kind === 'ck') return t('gateTitleCk');
    const step = pipeline && pipeline.step;
    if (step === 'awaiting_approval') return t('gateTitleApproval');
    return t('gateTitlePk');   // awaiting_plan_confirm / awaiting_path_confirm
}

function renderGateCard(evt) {
    const card = document.createElement('div');
    card.className = 'gate-card gate-' + evt.kind;
    // 不能声明同名局部 messagesContainer：会遮蔽全局 let 并触发 TDZ 自引用
    // （Cannot access 'messagesContainer' before initialization）。
    // 直接引用全局（initChatDom 已赋值）或回退 DOM。
    const mount = (typeof messagesContainer !== 'undefined' && messagesContainer)
        || document.getElementById('messages');
    if (!mount) return;

    if (evt.kind === 'pk') {
        const p = evt.pipeline || {};
        const planText = extractPlanFromPipeline(p);
        const phase = (p.phase_index != null && p.phase_total != null)
            ? t('gatePhase', { i: p.phase_index + 1, total: p.phase_total }) : '';

        const head = document.createElement('div');
        head.className = 'gate-card-head';
        head.textContent = gateStepTitle('pk', p);
        card.appendChild(head);

        if (phase) {
            const ph = document.createElement('div');
            ph.className = 'gate-card-phase';
            ph.textContent = phase;
            card.appendChild(ph);
        }
        if (planText) {
            const body = document.createElement('pre');
            body.className = 'gate-card-body';
            body.textContent = planText;
            card.appendChild(body);
        }
        // 6.5.3 artifact 计划视图：异步取回并展示（不阻塞卡片渲染）
        const artifactBox = document.createElement('div');
        artifactBox.className = 'gate-card-artifact';
        card.appendChild(artifactBox);
        loadArtifactView(p, artifactBox);
        // 操作区
        const actions = document.createElement('div');
        actions.className = 'gate-card-actions';

        const confirmBtn = document.createElement('button');
        confirmBtn.className = 'gate-btn gate-confirm';
        confirmBtn.textContent = t('confirmBtn');
        confirmBtn.addEventListener('click', () => {
            queueSynthPipelineReturn(p.id, 'confirm');
            card.replaceWith(doneBanner());
            notifyGateAction();
        });

        const rejectBtn = document.createElement('button');
        rejectBtn.className = 'gate-btn gate-reject';
        rejectBtn.textContent = t('rejectBtn');
        const opinion = document.createElement('input');
        opinion.type = 'text';
        opinion.className = 'gate-opinion';
        opinion.placeholder = t('rejectOpinionPh');
        rejectBtn.addEventListener('click', () => {
            queueSynthPipelineReturn(p.id, 'reject', opinion.value.trim() || undefined);
            card.replaceWith(doneBanner());
            notifyGateAction();
        });

        const regenBtn = document.createElement('button');
        regenBtn.className = 'gate-btn gate-regen';
        regenBtn.textContent = t('regenerateBtn');
        regenBtn.addEventListener('click', () => {
            queueSynthPipelineReturn(p.id, 'regenerate');
            card.replaceWith(doneBanner());
            notifyGateAction();
        });

        const abortBtn = document.createElement('button');
        abortBtn.className = 'gate-btn gate-abort';
        abortBtn.textContent = t('abortBtn');
        abortBtn.addEventListener('click', () => {
            queueSynthPipelineReturn(p.id, 'abort');
            card.replaceWith(doneBanner());
            notifyGateAction();
        });

        actions.append(confirmBtn, rejectBtn, opinion, regenBtn, abortBtn);
        card.appendChild(actions);

    } else if (evt.kind === 'ck') {
        const head = document.createElement('div');
        head.className = 'gate-card-head';
        head.textContent = gateStepTitle('ck');
        card.appendChild(head);

        const hint = document.createElement('div');
        hint.className = 'gate-card-phase';
        hint.textContent = t('gateContextParked');
        card.appendChild(hint);

        const editor = document.createElement('textarea');
        editor.className = 'gate-card-editor';
        editor.value = JSON.stringify(evt.context || {}, null, 2);

        const actions = document.createElement('div');
        actions.className = 'gate-card-actions';

        const amendBtn = document.createElement('button');
        amendBtn.className = 'gate-btn gate-confirm';
        amendBtn.textContent = t('amendBtn');
        amendBtn.addEventListener('click', async () => {
            try {
                const edited = JSON.parse(editor.value);
                await amendGateContext(evt.context_id, { context: edited });
                card.replaceWith(doneBanner());
                notifyGateAction();
            } catch (e) {
                editor.classList.add('gate-editor-err');
                showError(t('uploadFailed', { msg: e.message }));
            }
        });

        const rejectBtn = document.createElement('button');
        rejectBtn.className = 'gate-btn gate-reject';
        rejectBtn.textContent = t('rejectBtn');
        rejectBtn.addEventListener('click', () => {
            amendGateContext(evt.context_id, { context: { aborted: true } }).catch(() => {});
            card.replaceWith(doneBanner());
            notifyGateAction();
        });

        const abortBtn = document.createElement('button');
        abortBtn.className = 'gate-btn gate-abort';
        abortBtn.textContent = t('abortBtn');
        abortBtn.addEventListener('click', () => {
            amendGateContext(evt.context_id, { context: { aborted: true } }).catch(() => {});
            card.replaceWith(doneBanner());
            notifyGateAction();
        });

        actions.append(amendBtn, rejectBtn, abortBtn);
        card.append(editor, actions);
    } else {
        return;   // 未知类型不渲染
    }

    mount.appendChild(card);
}

function doneBanner() {
    const d = document.createElement('div');
    d.className = 'gate-done';
    d.textContent = t('gateActionDone');
    return d;
}

// 6.5.3 artifact 计划视图：异步取回 artifact 并渲染（不阻塞卡片渲染）
// p: synth_pipeline 对象（含 artifact_ref 或 id）
async function loadArtifactView(p, box) {
    if (!runtimeConfig.enableSynthLoop) return;
    const loading = document.createElement('div');
    loading.className = 'gate-artifact-loading';
    loading.textContent = t('artifactLoading');
    box.appendChild(loading);

    try {
        const items = [];
        if (p.artifact_ref) {
            try { items.push(await fetchArtifact(p.artifact_ref)); } catch (e) { /* 单条失败不影响列表 */ }
        }
        if (p.id) {
            try {
                const lst = await listPipelineArtifacts(p.id);
                if (lst && Array.isArray(lst.items)) items.push(...lst.items);
                else if (Array.isArray(lst)) items.push(...lst);
            } catch (e) { /* 列表端点可能未实现 */ }
        }

        box.removeChild(loading);
        const title = document.createElement('div');
        title.className = 'gate-artifact-title';
        title.textContent = t('artifactView');
        box.appendChild(title);

        if (!items.length) {
            const empty = document.createElement('div');
            empty.className = 'gate-artifact-empty';
            empty.textContent = t('artifactEmpty');
            box.appendChild(empty);
            return;
        }

        items.forEach((art) => {
            const node = renderArtifactNode(art);
            if (node) box.appendChild(node);
        });
    } catch (e) {
        if (loading.parentNode) loading.textContent = t('uploadFailed', { msg: e.message });
    }
}

// 渲染单个 artifact 节点：人读摘要（content）+ 可折叠完整数据（data）
function renderArtifactNode(art) {
    if (!art || typeof art !== 'object') return null;
    const wrap = document.createElement('div');
    wrap.className = 'gate-artifact-item';

    const name = document.createElement('div');
    name.className = 'gate-artifact-name';
    name.textContent = (art.name || art.id || t('artifactView'));
    wrap.appendChild(name);

    if (art.content) {
        const sum = document.createElement('div');
        sum.className = 'gate-artifact-summary';
        sum.textContent = art.content;
        wrap.appendChild(sum);
    }
    if (art.data != null) {
        const details = document.createElement('details');
        details.className = 'gate-artifact-data';
        const sumEl = document.createElement('summary');
        sumEl.textContent = t('artifactData');
        const pre = document.createElement('pre');
        pre.textContent = (typeof art.data === 'string') ? art.data : JSON.stringify(art.data, null, 2);
        details.append(sumEl, pre);
        wrap.appendChild(details);
    }
    return wrap;
}

// 用户操作闸后，通知 sl-chat 自动推进下一轮（空消息带回传）
function notifyGateAction() {
    document.dispatchEvent(new CustomEvent('gateAction', { detail: {} }));
}
