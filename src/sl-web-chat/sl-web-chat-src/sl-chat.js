// ========== sl-chat.js ==========
// 会话历史 / 资源渲染 / 文件上传 / 提交主链 / Clean / 初始化
// 裁剪自 tc-chat.js：删除 tc 免打扰轮（initQuietBridge）、AI: 指令解析、tc 发现/状态灯。
//   synth-loop 的闸（pk 三闸 / ck 上下文闸）由后端在 chat 响应字段里暴露，壳只渲染+回传，
//   协议解析权留后端（见 concept_zh.md §二）。
// 依赖（同 <script> 共享作用域）：t / runtimeConfig / buildSystemPrompts

// ---------- 会话状态 ----------
// §3.2.1 SYSTEM_PROMPTS 注入：作为 conversationHistory 起始的 system 消息（位置占位，最后一期定）
let conversationHistory = buildSystemPrompts().map((c) => ({ role: 'system', content: c }));
let pendingAttachments = [];
// synth-loop 会话标识：首轮不传 → 读响应头 x-synthloop-session-id 存入 → 后续轮复用（Header）
//   同时供 Phase 3 longdata 以 body.session_id 复用同一会话（见 concept §六 / 开发计划 2.2）
let synthSessionId = null;

// DOM 句柄（由 sl-integrate.js 在 DOMContentLoaded 后绑定；此处延迟取）
let messagesContainer, chatForm, userInput, statusElement, errorElement, attachmentsTray, uploadBtn, fileInput, cleanBtn;

// ---------- 资源渲染（<resources> 协议） ----------
const SECURITY = { whitelistEnabled: false, allowedHosts: [] };

function parseResources(content) {
    if (typeof content !== 'string') return null;
    const m = content.match(/^\s*<resources>([\s\S]*?)<\/resources>\s*$/);
    if (!m) return null;
    try {
        const arr = JSON.parse(m[1].trim().replace(/'/g, '"'));
        return Array.isArray(arr) ? arr : [arr];
    } catch (e) { return null; }
}

function detectType(url) {
    const u = String(url).split('?')[0].toLowerCase();
    if (/\.(png|jpe?g|gif|webp|avif|svg|bmp)$/.test(u)) return 'image';
    if (/\.(mp4|webm|ogg|mov|m4v)$/.test(u)) return 'video';
    if (/\.(mp3|wav|m4a|aac)$/.test(u)) return 'audio';
    if (/\.pdf$/.test(u)) return 'pdf';
    return 'webpage';
}

function safeUrl(url) {
    try {
        const u = new URL(url, location.href);
        if (u.protocol !== 'http:' && u.protocol !== 'https:') return null;
        if (SECURITY.whitelistEnabled && !SECURITY.allowedHosts.includes(u.hostname)) return null;
        return u.href;
    } catch (e) { return null; }
}

function fileName(url) {
    try {
        const u = new URL(url, location.href);
        const parts = u.pathname.split('/');
        return decodeURIComponent(parts[parts.length - 1]) || 'resource';
    } catch (e) { return 'resource'; }
}

function invalidResource(url) {
    const ph = document.createElement('div');
    ph.className = 'media-invalid';
    ph.textContent = t('invalidResource', url);
    return ph;
}

function brokenImage() {
    const ph = document.createElement('div');
    ph.className = 'media-broken';
    ph.textContent = t('brokenImage');
    return ph;
}

function openLink(url) {
    const a = document.createElement('a');
    a.href = url; a.target = '_blank'; a.rel = 'noopener noreferrer';
    a.className = 'media-open-link';
    a.textContent = t('openInNewTab');
    return a;
}

function renderResource(url) {
    const safe = safeUrl(url);
    if (!safe) return invalidResource(url);
    const type = detectType(safe);
    if (type === 'image') {
        const block = document.createElement('div');
        block.className = 'media-item media-image-wrap';
        const img = document.createElement('img');
        img.className = 'media-image'; img.loading = 'lazy'; img.alt = fileName(safe);
        img.addEventListener('error', () => img.replaceWith(brokenImage()));
        img.src = safe; block.appendChild(img); return block;
    }
    if (type === 'video') {
        const block = document.createElement('div'); block.className = 'media-item';
        const v = document.createElement('video'); v.className = 'media-video'; v.controls = true; v.preload = 'none'; v.src = safe;
        block.appendChild(v); return block;
    }
    if (type === 'audio') {
        const block = document.createElement('div'); block.className = 'media-item';
        const a = document.createElement('audio'); a.className = 'media-audio'; a.controls = true; a.preload = 'none'; a.src = safe;
        block.appendChild(a); return block;
    }
    const block = document.createElement('div'); block.className = 'media-item';
    const details = document.createElement('details'); details.className = 'media-embed';
    const summary = document.createElement('summary');
    summary.textContent = (type === 'pdf' ? t('mediaPdf') : t('mediaWeb')) + fileName(safe);
    const body = document.createElement('div'); body.className = 'media-embed-body';
    details.appendChild(summary); details.appendChild(body);
    details.addEventListener('toggle', () => {
        if (details.open && !body.dataset.built) {
            body.dataset.built = '1';
            const iframe = document.createElement('iframe');
            iframe.className = 'media-iframe'; iframe.sandbox = 'allow-scripts allow-same-origin';
            iframe.referrerPolicy = 'no-referrer'; iframe.src = safe;
            body.appendChild(iframe); body.appendChild(openLink(safe));
        }
    });
    block.appendChild(details); return block;
}

function renderGallery(list) {
    const gallery = document.createElement('div'); gallery.className = 'media-gallery';
    list.forEach((item) => {
        const url = typeof item === 'string' ? item : (item && item.url);
        if (!url) return; gallery.appendChild(renderResource(url));
    });
    return gallery;
}

function addMessage(role, content) {
    const list = parseResources(content);
    const messageDiv = document.createElement('div');
    messageDiv.className = list ? 'message resource-message' : `message ${role}-message`;
    if (list) messageDiv.appendChild(renderGallery(list));
    else messageDiv.textContent = content;
    messagesContainer.appendChild(messageDiv);
    messagesContainer.scrollTop = messagesContainer.scrollHeight;
}

function showError(message) {
    errorElement.textContent = message;
    errorElement.style.display = 'block';
}

// ---------- LLM 请求（非流式 + 流式） ----------
async function sendToLLM(messages) {
    statusElement.textContent = t('thinking');
    const requestHeaders = { ...runtimeConfig.headers };
    // 2.2 session_id 对齐：仅启用 synth-loop 时带 x-synthloop-session-id，后端识别为同一会话
    if (runtimeConfig.enableSynthLoop && synthSessionId) requestHeaders['x-synthloop-session-id'] = synthSessionId;
    const ac = new AbortController();
    const timer = setTimeout(() => ac.abort(), 30000);
    // 数据面临时区：发送前快照待注入 packet（消费即清空，避免下一轮重复带旧 packet）
    const pendingPacketSnapshot = runtimeConfig.enableSynthLoop ? getPendingPacketIds() : [];
    let response;
    try {
        response = await fetch(runtimeConfig.baseUrl, {
            method: 'POST', headers: requestHeaders,
            body: JSON.stringify({
                model: runtimeConfig.model, messages: messages,
                max_tokens: runtimeConfig.maxTokens, temperature: runtimeConfig.temperature, stream: true,
                // 数据面注入：仅启用 synth-loop 时把已提交 packet id 透传给 chat（后端 _inject_packets 消费）
                // 注意：这是【数据面】引用机制，不是 ck 闸的"上下文编辑"（5.5 纠偏）
                // 4.2 pk 三闸回传：仅启用 synth-loop 时回带 synth_pipeline:{id,action}
                //   注意必须包成 synth_pipeline 对象（后端 body.get('synth_pipeline')），
                //   不能把 {id,action} 直接展开到顶层，否则后端拿不到回传、相位不推进。
                ...(runtimeConfig.enableSynthLoop ? {
                    packets: pendingPacketSnapshot,
                    ...(() => {
                        const ret = takePendingSynthPipelineReturn();
                        return ret ? { synth_pipeline: ret } : {};
                    })()
                } : {})
            }),
            signal: ac.signal
        });
    } catch (e) { clearTimeout(timer); throw e; }
    if (pendingPacketSnapshot.length) clearPendingPacketIds();   // 发送即消费
    clearTimeout(timer);
    if (!response.ok) {
        let msg = `HTTP ${response.status}`;
        try {
            const errData = await response.json();
            if (errData && errData.error && errData.error.message) msg = errData.error.message;
        } catch (e) { /* ignore */ }
        throw new Error(msg);
    }
    // 2.2 读回 session：仅启用 synth-loop 时后端注入 x-synthloop-session-id（首轮新建 / 后续复用）
    if (runtimeConfig.enableSynthLoop) {
        const returnedSession = response.headers.get('x-synthloop-session-id');
        if (returnedSession) synthSessionId = returnedSession;
    }
    const ct = response.headers.get('content-type') || '';
    if (ct.includes('text/event-stream')) {
        // 流式：纯文本增量，无 synth_pipeline/gate 顶层字段（相位/闸分支为非流式，见 chat.py:301-331）
        const full = await readStreaming(response);
        if (typeof renderPendingGateCards === 'function') renderPendingGateCards();
        return full;
    }
    const data = await response.json();
    if (data.error) throw new Error(data.error.message || 'API返回错误');
    // 4.x 闸字段解析：响应（非流式）可能携带 synth_pipeline（pk 三闸）或 gate:"pending"（ck 推理闸）
    //   当前仅解析分流（UI 渲染留 Phase 6.5）；解析结果由 Phase 6.5 的 renderGateCard 消费
    if (typeof parseGateFromResponse === 'function') {
        const gate = parseGateFromResponse(data);
        if (gate && gate.kind) {
            // 暂存到会话级队列，供 Phase 6.5 UI 拉取渲染（此处不渲染，遵守"UI 留后"指令）
            pushGateEvent(gate);
        }
    }
    const message = (data.choices && data.choices[0] && data.choices[0].message) || {};
    const content = message.content || '';
    addMessage('assistant', content);
    return content;
}

// 流式读取 SSE；收尾时 <resources> 整体替换为画廊。
// §12.3.10 流结束兜底：对 fullText 在 done 后由 parseDirectives（含 EOL 兜底）统一收口。
async function readStreaming(response) {
    statusElement.textContent = t('streaming');
    const bubble = document.createElement('div');
    bubble.className = 'message assistant-message';
    bubble.setAttribute('aria-live', 'off');
    messagesContainer.appendChild(bubble);
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = ''; let fullText = ''; let potentialResource = false;
    const flush = () => { messagesContainer.scrollTop = messagesContainer.scrollHeight; };
    while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        let idx;
        while ((idx = buffer.indexOf('\n\n')) !== -1) {
            const rawEvent = buffer.slice(0, idx); buffer = buffer.slice(idx + 2);
            const line = rawEvent.trim();
            if (!line.startsWith('data:')) continue;
            const dataStr = line.slice(5).trim();
            if (dataStr === '[DONE]') continue;
            let evt; try { evt = JSON.parse(dataStr); } catch (e) { continue; }
            const choice = (evt.choices && evt.choices[0]) || {};
            const delta = choice.delta || {};
            if (delta.content) {
                fullText += delta.content;
                const trimmed = fullText.trimStart();
                if (/^\s*<resources[\s>]/.test(trimmed)) {
                    potentialResource = true; bubble.textContent = '';
                } else if (!potentialResource) {
                    bubble.textContent = fullText;
                }
                flush();
            }
        }
    }
    if (potentialResource) {
        const list = parseResources(fullText);
        if (list) {
            const galleryMsg = document.createElement('div');
            galleryMsg.className = 'message resource-message';
            galleryMsg.appendChild(renderGallery(list));
            bubble.replaceWith(galleryMsg);
        } else { bubble.textContent = fullText; }
    }
    bubble.setAttribute('aria-live', 'polite');
    return fullText; // §12.3.10：调用方可对 fullText 跑 parseDirectives 收尾
}

// ---------- 文件上传 + 多模态附件 ----------
function resolveUploadUrl() {
    const cdn = (runtimeConfig.cdnUrl || '').trim().replace(/\/+$/, '');
    if (cdn) return cdn + '/upload';
    try {
        const b = new URL(runtimeConfig.baseUrl, location.href);
        return (b.origin || location.origin) + '/upload';
    } catch (e) { return location.origin + '/upload'; }
}

function mediaPartFor(type, url) {
    if (type === 'image') return { type: 'image_url', image_url: { url } };
    if (type === 'video') return { type: 'video_url', video_url: { url } };
    if (type === 'audio') return { type: 'audio_url', audio_url: { url } };
    return { type: 'file_url', file_url: { url } };
}

function makeChip(att, withRemove, index) {
    const chip = document.createElement('div'); chip.className = 'att-chip att-' + att.type;
    if (att.type === 'image') {
        const img = document.createElement('img'); img.src = att.url; img.alt = att.name; img.className = 'att-thumb';
        chip.appendChild(img);
    } else {
        const icon = document.createElement('span'); icon.className = 'att-icon';
        icon.textContent = att.type === 'video' ? '🎬' : att.type === 'audio' ? '🔊' : '📄';
        chip.appendChild(icon);
    }
    const name = document.createElement('span'); name.className = 'att-name'; name.textContent = att.name; name.title = att.name;
    chip.appendChild(name);
    if (withRemove) {
        const x = document.createElement('button'); x.type = 'button'; x.className = 'att-remove';
        x.setAttribute('aria-label', t('removeAtt', att.name)); x.textContent = '×';
        x.addEventListener('click', () => removeAttachment(index));
        chip.appendChild(x);
    }
    return chip;
}

function renderAttachmentsTray() {
    attachmentsTray.innerHTML = '';
    if (pendingAttachments.length === 0) { attachmentsTray.style.display = 'none'; return; }
    attachmentsTray.style.display = 'flex';
    pendingAttachments.forEach((att, i) => attachmentsTray.appendChild(makeChip(att, true, i)));
}

function removeAttachment(i) { pendingAttachments.splice(i, 1); renderAttachmentsTray(); }

function addUserBubble(text, attachments) {
    const div = document.createElement('div'); div.className = 'message user-message';
    if (text) { const p = document.createElement('div'); p.textContent = text; div.appendChild(p); }
    if (attachments && attachments.length) {
        const tray = document.createElement('div'); tray.className = 'att-inline';
        attachments.forEach((att) => tray.appendChild(makeChip(att, false, -1)));
        div.appendChild(tray);
    }
    messagesContainer.appendChild(div);
    messagesContainer.scrollTop = messagesContainer.scrollHeight;
}

async function uploadFile(file) {
    // 选项 A：关闭 synth-loop 时走纯 OpenAI 多模态标准——文件读成 base64 data URL 内联，不依赖 /upload 端点
    if (!runtimeConfig.enableSynthLoop) {
        try {
            const dataUrl = await readFileAsDataUrl(file);
            pendingAttachments.push({ url: dataUrl, name: file.name, type: detectType(file.name) });
            renderAttachmentsTray();
            statusElement.textContent = t('statusReady');
        } catch (e) {
            console.error('读取文件失败:', e);
            showError(t('uploadFailed', { msg: e.message }));
            statusElement.textContent = t('statusReady');
        }
        return;
    }
    // 启用 synth-loop：走数据面临时区 packets（6.5.1.x）——不是 /upload，也不是内联 attachment
    // 选文件 → submitPacket 拿 packet_id → 自动进 pendingPacketIds → 发送时 sendToLLM 注入 packets:[id]
    // 壳不维护 packets 列表（后端 TTL 自动维护），仅给计数反馈
    statusElement.textContent = t('uploading', file.name);
    try {
        const dataUrl = await readFileAsDataUrl(file);
        const type = packetTypeFromFile(file);   // 扩展名 → packet type
        const id = await submitPacket({
            type,
            payload: { name: file.name, mime: file.type || 'application/octet-stream', data: dataUrl },
            meta: { source: 'sl-web-chat-upload' }
        });
        if (!id) throw new Error('packet response missing packet_id');
        statusElement.textContent = t('packetQueued', getPendingPacketIds().length);
    } catch (e) {
        console.error('提交 packet 失败:', e);
        showError(t('uploadFailed', { msg: e.message }));
        statusElement.textContent = t('statusReady');
    }
}

// 扩展名 → packet type（synth-loop /v1/packets 的 type 命名空间）
function packetTypeFromFile(file) {
    const ext = (file.name.split('.').pop() || '').toLowerCase();
    const map = {
        txt: 'doc', md: 'doc', pdf: 'doc', doc: 'doc', docx: 'doc',
        png: 'image', jpg: 'image', jpeg: 'image', gif: 'image', webp: 'image',
        mp3: 'audio', wav: 'audio', ogg: 'audio',
        mp4: 'video', webm: 'video', mov: 'video',
        json: 'data', csv: 'data', xml: 'data'
    };
    return map[ext] || 'doc';
}

function readFileAsDataUrl(file) {
    return new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(reader.result);
        reader.onerror = () => reject(reader.error || new Error('FileReader error'));
        reader.readAsDataURL(file);
    });
}

// ---------- 处理一轮 LLM 完整文本：纯文本呈现 ----------
// synth-loop 的闸（pk/ck）不走前端解析，由后端在 chat 响应字段暴露，壳只渲染+回传。
async function handleAssistantTurn(fullText) {
    if (fullText && fullText.trim()) {
        addMessage('assistant', fullText);
    }
}

// ---------- 提交主链 ----------
// 核心提交逻辑（userMessage 可为空：闸回传推进时为空文本，但带 pendingSynthPipelineReturn）
async function submitChat(userMessage) {
    if (!userMessage && pendingAttachments.length === 0 && getPendingPacketIds().length === 0 && !hasPendingSynthPipelineReturn()) return;
    userInput.disabled = true;
    const submitBtn = chatForm.querySelector('button[type="submit"]');
    submitBtn.disabled = true;
    let content;
    if (pendingAttachments.length === 0) content = userMessage;
    else {
        content = [{ type: 'text', text: userMessage }];
        pendingAttachments.forEach((att) => content.push(mediaPartFor(att.type, att.url)));
    }
    try {
        addUserBubble(userMessage, pendingAttachments);
        conversationHistory.push({ role: 'user', content });
        userInput.value = ''; userInput.style.height = 'auto';
        pendingAttachments = []; renderAttachmentsTray();
        // 渲染由 sendToLLM 内部完成（非流式 addMessage / 流式 readStreaming bubble），
        // 此处不再调用 handleAssistantTurn，避免"每条消息渲染两条回复"的重复。
        const assistantResponse = await sendToLLM(conversationHistory);
        conversationHistory.push({ role: 'assistant', content: assistantResponse });
        // 6.5.2：每轮回答后渲染待处理闸卡片（消费 pendingGateEvents）
        renderPendingGateCards();
        const MAX_HISTORY = 100;
        if (conversationHistory.length > MAX_HISTORY) {
            conversationHistory = conversationHistory.slice(-MAX_HISTORY);
        }
    } catch (error) {
        console.error('请求失败:', error);
        let detail;
        // §12.3.9：fetch 网络层失败（TypeError）→ 说人话，不污染协议层
        if (error instanceof TypeError || error.name === 'TypeError') {
            detail = '无法连接到 ' + runtimeConfig.baseUrl + '。\n' +
                '• 确认后端已启动\n' +
                '• 若以 file:// 双击打开，请将 localhost 改为 127.0.0.1\n' +
                '• 或直接用浏览器访问 http://127.0.0.1:8000/ （同源，免跨域）';
        } else { detail = error.message; }
        showError(t('requestFailed', { msg: detail }));
    } finally {
        userInput.disabled = false; submitBtn.disabled = false;
        userInput.focus(); statusElement.textContent = t('statusReady');
    }
}

function bindChatForm() {
    chatForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        await submitChat(userInput.value.trim());
    });
    // 6.5.2：闸卡片操作后自动推进下一相位（空消息带回传）
    document.addEventListener('gateAction', () => {
        submitChat('');
    });
}

// ---------- Clean：清空会话 ----------
function bindCleanBtn() {
    cleanBtn.addEventListener('click', () => {
        messagesContainer.innerHTML = '';
        pendingAttachments = []; renderAttachmentsTray();
        errorElement.style.display = 'none';
        conversationHistory = buildSystemPrompts().map((c) => ({ role: 'system', content: c }));
        synthSessionId = null;   // 2.2 清空会话同时重置 session，避免串会话
        clearPendingPacketIds(); // 3.1 清空待注入 packet 队列
        pendingGateEvents = [];  // 4.x 清空未消费的闸事件
        resetDataPanelState();   // 6.5.1 清空数据面本地条目（后端按 session 失效，下次打开重拉）
        statusElement.textContent = t('statusReady');
        userInput.focus();
    });
}

// ---------- 初始化 ----------
function bindUpload() {
    uploadBtn.addEventListener('click', () => fileInput.click());
    fileInput.addEventListener('change', async () => {
        const files = Array.from(fileInput.files || []);
        fileInput.value = '';
        for (const f of files) await uploadFile(f);
    });
}

function autoGrow() {
    userInput.style.height = 'auto';
    const max = Math.round(window.innerHeight * 0.4);
    userInput.style.height = Math.min(userInput.scrollHeight, max) + 'px';
}

function bindInput() {
    userInput.addEventListener('input', autoGrow);
    userInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) {
            e.preventDefault(); chatForm.requestSubmit();
        }
    });
}

// 由 sl-integrate.js 在 DOM 就绪后调用：抓取 DOM 句柄 + 绑定事件
function initChatDom() {
    messagesContainer = document.getElementById('messages');
    chatForm = document.getElementById('chatForm');
    userInput = document.getElementById('userInput');
    statusElement = document.getElementById('status');
    errorElement = document.getElementById('error');
    attachmentsTray = document.getElementById('attachmentsTray');
    uploadBtn = document.getElementById('uploadBtn');
    fileInput = document.getElementById('fileInput');
    cleanBtn = document.getElementById('cleanBtn');
    bindChatForm(); bindCleanBtn(); bindUpload(); bindInput();
}

async function onAppLoad() {
    applyLang(currentLang);
    if (typeof loadConfigToForm === 'function') loadConfigToForm();
    // 初始化会话标识：数据面（longdata/packets）不依赖"先发 chat"，开屏即具备稳定 session
    if (!synthSessionId && runtimeConfig.enableSynthLoop) {
        synthSessionId = 's_local_' + Math.random().toString(36).slice(2, 10);
    }
    initChatDom();
    addMessage('assistant', t('greeting'));
    statusElement.textContent = t('statusReady');
}

// 顶层函数声明：浏览器内联（module 为 undefined 时 module.exports 不执行）下，
// 也必须让 sl-context.js / sl-integrate.js 能通过共享作用域访问到 getSynthSessionId。
// （否则 addLongdata 等调用 ReferenceError：getSynthSessionId is not defined）
function getSynthSessionId() { return synthSessionId; }
function setSynthSessionId(id) { synthSessionId = id; }

if (typeof module !== 'undefined' && module.exports) {
    module.exports = {
        handleAssistantTurn, onAppLoad, initChatDom,
        getConversationHistory: () => conversationHistory,
        setConversationHistory: (h) => { conversationHistory = h; },
        getSynthSessionId, setSynthSessionId
    };
}
