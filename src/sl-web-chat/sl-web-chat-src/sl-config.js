// ========== sl-config.js ==========
// 配置状态管理 + 多语言（i18n）+ SYSTEM_PROMPTS 占位
// 裁剪自 tc-config.js：删除 tc 桥接配置项 / 双令牌头 / tc 系统提示段。
// synth-loop 是 OpenAI 兼容网关，壳只需 baseUrl + 通用 headers + 语言 prompt。

// ---------- 配置持久化 ----------
const CONFIG_KEY = 'sl-web-chat-config';
const DEFAULT_CONFIG = {
    baseUrl: '/v1/chat/completions',
    model: 'default-model',
    headers: { 'Content-Type': 'application/json' },
    cdnUrl: '',
    maxTokens: 1000,
    temperature: 0.7,
    enableSynthLoop: true
};

function loadConfig() {
    try {
        const raw = localStorage.getItem(CONFIG_KEY);
        if (raw) {
            const obj = JSON.parse(raw);
            return {
                ...DEFAULT_CONFIG,
                ...obj,
                headers: { 'Content-Type': 'application/json', ...(obj.headers || {}) }
            };
        }
    } catch (e) { /* 解析失败回退默认 */ }
    return { ...DEFAULT_CONFIG };
}

function saveConfig(config) {
    try { localStorage.setItem(CONFIG_KEY, JSON.stringify(config)); } catch (e) { /* storage 满则静默失败 */ }
}

let runtimeConfig = loadConfig();

// ---------- 语言注册表 + 多语言文案 ----------
// 注意：LANGS / I18N 不再硬编码于此，改由构建时从 i18n.json 读取并按 --lang 注入到脚本段
// （见 build.js：读 i18n.json → 拼 `const LANGS=...; const I18N=...;` 注入）。
// 运行时此处仅消费全局 LANGS / I18N（同 <script> 共享作用域）。
// 加语言 = 改 i18n.json 一行，无需动此文件。
function langList() { return Object.keys(LANGS).map((k) => ({ code: k, ...LANGS[k] })); }

// 默认语言：由注入词典推导——单语包只有一个键，默认即为该语言；双包回退 en
let currentLang = (I18N && Object.keys(I18N).length === 1) ? Object.keys(I18N)[0] : 'en';

function t(key, params) {
    let s = I18N[currentLang] && I18N[currentLang][key];
    if (s === undefined) {
        // 双包才有 en 回退；单语包无 en 键，直接回退 key 本身（避免读 undefined['key'] 抛 TypeError）
        s = (I18N.en && I18N.en[key] !== undefined) ? I18N.en[key] : key;
    }
    if (typeof s === 'function') return s(params);
    if (params && typeof params === 'object') {
        for (const k in params) s = s.replace(new RegExp('\\{' + k + '\\}', 'g'), params[k]);
    }
    return s;
}

// 语言 prompt 随下拉变（§3.5 / §3.2.1 第二条）；LANGS 已是注册表对象
function currentLanguagePrompt() {
    const lang = LANGS[currentLang] || LANGS.zh;
    return lang ? lang.prompt : '';
}

// 遍历 LANGS 注册表生成 <option>（§3.5：语言是数据不是分支）
function buildLangOptions() {
    return langList().map((l) =>
        `<option value="${l.code}">${l.label} · ${l.name}</option>`).join('');
}

// ---------- SYSTEM_PROMPTS（语种注入） ----------
// synth-loop 是通用 OpenAI 兼容网关，壳只注入语种指令，不预置任何工具提示。
function buildSystemPrompts() {
    return [currentLanguagePrompt()];   // 语种指令注入
}

// ---------- 语言应用（§3.5：语言是数据不是分支，查表回退） ----------
// 单语版（注入词典仅一个键）：隐藏语言下拉框（头部 + 面板），避免出现无效切换器
function isSingleLang() {
    return !!(I18N && Object.keys(I18N).length === 1);
}

function applyLang(lang) {
    currentLang = lang || (isSingleLang() ? Object.keys(I18N)[0] : 'en');
    document.documentElement.lang = (currentLang === 'zh') ? 'zh-CN' : 'en';
    document.querySelectorAll('[data-i18n],[data-i18n-ph],[data-i18n-title]').forEach((el) => {
        if (el.hasAttribute('data-i18n')) el.textContent = t(el.getAttribute('data-i18n'));
        if (el.hasAttribute('data-i18n-ph')) el.placeholder = t(el.getAttribute('data-i18n-ph'));
        if (el.hasAttribute('data-i18n-title')) el.title = t(el.getAttribute('data-i18n-title'));
    });
    // 单语版不显示语言配置（下拉 + 所在行）；双包才同步 options 并置选中项
    const single = isSingleLang();
    ['langSelect', 'langSelectCfg'].forEach((id) => {
        const sel = document.getElementById(id);
        if (!sel) return;
        sel.style.display = single ? 'none' : '';
        if (!single) {
            if (!sel.options.length) sel.innerHTML = buildLangOptions();
            sel.value = currentLang;
        }
    });
    if (single) {
        const langRow = document.getElementById('configLangRow');
        if (langRow) langRow.style.display = 'none';
    }
}

if (typeof module !== 'undefined' && module.exports) {
    module.exports = {
        DEFAULT_CONFIG, loadConfig, saveConfig,
        LANGS, I18N, t, currentLanguagePrompt,
        SYSTEM_PROMPTS_STATIC, buildSystemPrompts,
        applyLang, bindLangButtons,
        getRuntimeConfig: () => runtimeConfig,
        setRuntimeConfig: (c) => { runtimeConfig = c; }
    };
}
