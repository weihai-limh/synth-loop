// ========== sl-integrate.js ==========
// 唯一胶水层：知道 HTML 结构，绑定所有 DOM 事件，串起各源模块。
// 裁剪自 tc-integrate.js：删除 tc 专属配置字段（端点/令牌/scope/人闸三态下拉），
//   改由 sl 的闸管理 UI（sl-gate.js）与上下文编辑 UI（sl-context.js）承担。
// 依赖（同 <script> 共享作用域）：runtimeConfig / saveConfig / loadConfigToForm /
//   t / LANGS / applyLang / bindLangButtons / onAppLoad / showError

// ---------- 配置面板（仅通用项：baseUrl / model / headers / cdn） ----------
function bindConfigPanel() {
    const toggleConfigBtn = document.getElementById('toggleConfig');
    const configPanel = document.getElementById('configPanel');
    const toggleHeadersBtn = document.getElementById('toggleHeaders');
    const headersEditor = document.getElementById('headersEditor');
    const toggleCdnBtn = document.getElementById('toggleCdn');
    const cdnEditor = document.getElementById('cdnEditor');
    const saveConfigBtn = document.getElementById('saveConfig');
    const cancelConfigBtn = document.getElementById('cancelConfig');
    const cfgBaseUrl = document.getElementById('cfgBaseUrl');
    const cfgModel = document.getElementById('cfgModel');
    const cfgHeaders = document.getElementById('cfgHeaders');
    const cfgCdn = document.getElementById('cfgCdn');
    const cfgEnableSynthLoop = document.getElementById('cfgEnableSynthLoop');
    const errorElement = document.getElementById('error');

    loadConfigToForm = function () {
        cfgBaseUrl.value = runtimeConfig.baseUrl;
        cfgModel.value = runtimeConfig.model;
        cfgHeaders.value = JSON.stringify(runtimeConfig.headers, null, 2);
        cfgCdn.value = JSON.stringify({ cdn_url: runtimeConfig.cdnUrl }, null, 2);
        if (cfgEnableSynthLoop) cfgEnableSynthLoop.checked = !!runtimeConfig.enableSynthLoop;
        syncLangSelect();
        applyLang(currentLang);
        applySynthLoopMode();
    };

    toggleConfigBtn.addEventListener('click', () => {
        if (!configPanel.classList.contains('show')) loadConfigToForm();
        configPanel.classList.toggle('show');
    });
    toggleHeadersBtn.addEventListener('click', () => headersEditor.classList.toggle('show'));
    toggleCdnBtn.addEventListener('click', () => cdnEditor.classList.toggle('show'));
    cancelConfigBtn.addEventListener('click', () => {
        configPanel.classList.remove('show'); headersEditor.classList.remove('show');
    });

    saveConfigBtn.addEventListener('click', () => {
        const baseUrl = cfgBaseUrl.value.trim();
        if (!baseUrl) { showError(t('baseUrlEmpty')); return; }
        try {
            const parsedHeaders = JSON.parse(cfgHeaders.value.trim());
            runtimeConfig.baseUrl = baseUrl;
            runtimeConfig.model = cfgModel.value.trim() || 'default-model';
            runtimeConfig.headers = parsedHeaders;
            if (cfgEnableSynthLoop) runtimeConfig.enableSynthLoop = !!cfgEnableSynthLoop.checked;
            try {
                const parsedCdn = JSON.parse(cfgCdn.value.trim());
                runtimeConfig.cdnUrl = (parsedCdn.cdn_url || '').trim();
            } catch (e) { runtimeConfig.cdnUrl = ''; }

            errorElement.textContent = t('configSaved');
            errorElement.style.background = '#e8f5e9';
            errorElement.style.color = '#2e7d32';
            errorElement.style.display = 'block';
            setTimeout(() => {
                errorElement.style.display = 'none';
                errorElement.style.background = '#ffebee';
                errorElement.style.color = '#d32f2f';
            }, 2000);
            configPanel.classList.remove('show');
            headersEditor.classList.remove('show');
            saveConfig(runtimeConfig);
        } catch (e) {
            showError(t('headersJsonErr', e.message));
        }
    });
}

// 填充并同步所有语言下拉（头部 langSelect + 面板 langSelectCfg）
function syncLangSelect() {
    ['langSelect', 'langSelectCfg'].forEach((id) => {
        const el = document.getElementById(id);
        if (el) {
            if (!el.options.length) el.innerHTML = buildLangOptions();
            el.value = currentLang;
        }
    });
}

// ---------- 语言下拉（头部 + 面板双实例都绑） ----------
function bindUiControls() {
    ['langSelect', 'langSelectCfg'].forEach((id) => {
        const el = document.getElementById(id);
        if (el) el.addEventListener('change', () => applyLang(el.value));
    });
}

// ---------- synth-loop 模式开关：显隐仅 synth 专属的 UI ----------
// data-sl-only 标记的元素（📂 Data 按钮 / Configure CDN / synth 开关行本身不被隐藏——它是开关）
function applySynthLoopMode() {
    const on = !!runtimeConfig.enableSynthLoop;
    document.querySelectorAll('[data-sl-only]').forEach((el) => {
        el.style.display = on ? '' : 'none';
    });
    // 关闭时若数据面正展开则收起
    if (!on) {
        const panel = document.getElementById('dataPanel');
        if (panel) panel.classList.remove('show');
    }
}

// ---------- 数据面：永久区 longdata 常驻侧栏（Phase 6.5.1） ----------
// 形态：侧栏列表 + 添加（基于类型建条目→填文本→提交→id 映射）/ 删除（关联 id→卸载）
// 临时区 packets 不在此面板（走 uploadBtn，见 bindUploadBtn）。
let longdataEntries = [];   // [{ localId, id, type, content }]
let localSeq = 0;

function renderLongdataList() {
    const list = document.getElementById('longdataList');
    if (!list) return;
    list.innerHTML = '';
    if (longdataEntries.length === 0) {
        const empty = document.createElement('div');
        empty.className = 'ld-empty';
        empty.textContent = t('ldEmpty');
        list.appendChild(empty);
        return;
    }
    longdataEntries.forEach((e) => {
        const item = document.createElement('div');
        item.className = 'ld-item';
        const meta = document.createElement('div');
        meta.className = 'ld-item-meta';
        const type = document.createElement('span');
        type.className = 'ld-type';
        type.textContent = e.type;
        const del = document.createElement('button');
        del.className = 'ld-del';
        del.textContent = '🗑';
        del.title = t('deleteEntry');
        del.addEventListener('click', () => removeLongdata(e.localId));
        meta.appendChild(type);
        meta.appendChild(del);
        const content = document.createElement('div');
        content.className = 'ld-content';
        content.textContent = e.content;
        item.appendChild(meta);
        item.appendChild(content);
        list.appendChild(item);
    });
}

function appendLongdataForm() {
    const list = document.getElementById('longdataList');
    if (!list) return;
    if (list.querySelector('.ld-form')) return;   // 已有一个待填表单
    const form = document.createElement('div');
    form.className = 'ld-form';
    form.innerHTML =
        '<select class="ld-type-select">' +
        '  <option value="doc">' + t('typeDoc') + '</option>' +
        '  <option value="memory">' + t('typeMemory') + '</option>' +
        '</select>' +
        '<textarea class="ld-content-input" placeholder="' + t('ldContentPh') + '"></textarea>' +
        '<div class="ld-form-actions">' +
        '  <button class="ld-form-submit">' + t('submitEntry') + '</button>' +
        '  <button class="ld-form-cancel">' + t('cancelEntry') + '</button>' +
        '</div>';
    const ta = form.querySelector('.ld-content-input');
    form.querySelector('.ld-form-submit').addEventListener('click', async () => {
        const content = ta.value.trim();
        const type = form.querySelector('.ld-type-select').value;
        if (!content) { ta.focus(); return; }
        try {
            const r = await addLongdata({ type, content, session_id: getSynthSessionId() });
            const id = (r && r.id) || ('ld_' + (++localSeq));
            longdataEntries.push({ localId: ++localSeq, id, type, content });
            renderLongdataList();
        } catch (err) {
            showError(t('ldAddErr', { msg: err.message }));
        }
    });
    form.querySelector('.ld-form-cancel').addEventListener('click', () => form.remove());
    list.insertBefore(form, list.firstChild);
    ta.focus();
}

async function removeLongdata(localId) {
    const idx = longdataEntries.findIndex((e) => e.localId === localId);
    if (idx === -1) return;
    const entry = longdataEntries[idx];
    try {
        await deleteLongdata({ id: entry.id, session_id: getSynthSessionId() });
        longdataEntries.splice(idx, 1);
        renderLongdataList();
    } catch (err) {
        showError(t('ldDelErr', { msg: err.message }));
    }
}

async function refreshLongdataList() {
    try {
        const resp = await listLongdata(getSynthSessionId());
        // listLongdata 返回 { session_id, items:[...] }；兼容直接数组
        const items = (resp && Array.isArray(resp.items)) ? resp.items
                    : (Array.isArray(resp) ? resp : []);
        longdataEntries = items.map((it) => ({
            localId: ++localSeq,
            id: it.id,
            type: it.type,
            content: it.content
        }));
    } catch (err) {
        longdataEntries = [];
    }
    renderLongdataList();
}

// Clean 时调用：清空本地 entries（后端按 session 失效，下次打开重新拉取）
function resetDataPanelState() {
    longdataEntries = [];
    localSeq = 0;
    renderLongdataList();
}

function bindDataPanel() {
    const toggleBtn = document.getElementById('toggleDataPanel');
    const panel = document.getElementById('dataPanel');
    const addBtn = document.getElementById('addLongdataBtn');
    if (toggleBtn && panel) {
        toggleBtn.addEventListener('click', () => {
            if (!runtimeConfig.enableSynthLoop) return;   // 纯 OpenAI 模式无数据面
            const showing = panel.classList.toggle('show');
            if (showing) refreshLongdataList();
        });
    }
    if (addBtn) addBtn.addEventListener('click', appendLongdataForm);
    renderLongdataList();
}

// ---------- 全部绑定 + 启动 ----------
function bootSlWebChat() {
    bindConfigPanel();
    bindUiControls();
    bindDataPanel();
    // 聊天 DOM + 事件由 sl-chat.js 的 initChatDom 负责（它也在 onAppLoad 调）
    window.addEventListener('DOMContentLoaded', () => {
        onAppLoad();
    });
}

if (typeof module !== 'undefined' && module.exports) {
    module.exports = { bindConfigPanel, bindUiControls, bootSlWebChat };
}
