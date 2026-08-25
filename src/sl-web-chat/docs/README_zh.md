# sl-web-chat

一个单文件的聊天 Web 壳：双击即开，对接 synth-loop 后端。它既是纯 OpenAI 风格聊天界面，也承载 synth-loop 的**数据面**（长期/临时上下文）与**闸管理**（相位三闸、推理闸）能力。

## 快速启动（3 步）

1. **打开**：双击 `sl-web-chat.html`（或托管到静态服务器，同源打开 `http://127.0.0.1:13155/`）。推荐同源托管，体验最稳。
2. **配后端**：点右上角 ⚙️，填入后端 Base URL（如 `http://127.0.0.1:13155/v1/chat/completions`）和必要的请求头（API Key 走这里）。勾选「启用 synth-loop 服务」可开启数据面与闸能力。
3. **对话**：在输入框打字，`Enter` 发送；点 📎 上传多模态文件；`Clean` 清屏重来；双包可切语言（单语包自动隐藏语言下拉）。

> 想立刻体验？先起 `mock-server`（`python main.py`，监听 `:13155`），按上面填 Base URL 即可全功能演练——无需真实后端。

---

## 目录结构

```
sl-web-chat/
├── sl-web-chat.html              # ★ 双包制品（唯一分发交付物，双击即开）
├── sl-web-chat_zh.html           # 中文单语制品
├── sl-web-chat_en.html           # 英文单语制品
├── README_zh.md                  # 本文档（概述 + 能力状态）
├── user-manual_zh.md             # 用户手册（面向最终用户）
├── docs/                         # concept / development-plan / phase7-mock / GIT-BASELINE
├── mock-server/                  # 本地联调 mock（1:1 契约模拟，无后端时也能全功能演练）
│   ├── main.py
│   └── test_mock.py
└── sl-web-chat-src/              # ★ 源文件（进版本库，不进分发制品）
    ├── sl-config.js              # 配置状态 + 语言注册表 + I18N
    ├── sl-gate.js                # 闸数据链接层 + 闸卡片 UI（ck 推理闸 / pk 三闸）
    ├── sl-context.js             # 数据面（packets 临时区 + longdata 永久区）
    ├── sl-chat.js                # 会话历史 / 渲染 / submit / Clean
    ├── sl-integrate.js           # 唯一胶水层（按序内联进制品 <script>）
    ├── shell.html                # 外壳（DOM + CSS）
    ├── i18n.json                 # 文案词典（注入 build 时的语言分支）
    └── build.js                  # node 零依赖拼接脚本 → 生成三个制品
```

> **源与制品纪律**：`sl-web-chat-src/` 是源（进版本库），`sl-web-chat*.html` 是制品（唯一分发交付物），由 `node sl-web-chat-src/build.js` 零依赖拼接生成。制品可由源重建；仓库丢 html 可重建，丢 `sl-web-chat-src/` 才真丢。分发时只发 html。

---

## 能力实现状态

依据 `concept_zh.md` 的能力契约：

| 能力 | 状态 | 说明 |
|---|---|---|
| ① 聊天主链路 | ✅ 已实现 | OpenAI 兼容 `/v1/chat/completions`，流式优先 + 非流式降级 |
| ② 数据面 | ✅ 已实现 | 永久区 `longdata` 增删列（常驻面板）+ 临时区 `packets` 上传（📎 uploadBtn），随会话透传给后端 |
| ③ 闸管理 | ✅ 已实现 | ck 推理闸（`/chatgate` 编辑上下文后 amend）+ pk 三闸（`synth_pipeline` confirm / reject / abort） |
| ④ 产物视图 | ✅ 已实现 | 相位 plan / path / result artifact 取回渲染（`/api/v1/artifacts`） |
| ⑤ 多语言 | ✅ 已实现 | `LANGS` 注册表驱动；双包可切语言，单语包自动隐藏语言下拉 |
| ⑥ 会话管理 | ✅ 已实现 | `x-synthloop-session-id` 自动生成/复用；`Clean` 重置会话 |

**向后兼容**：不勾选「启用 synth-loop 服务」时，行为与纯 OpenAI 聊天完全一致；synth-loop 能力为可选配置项。

**不实现项**：
- path 可视化编辑器：初版仅支持文本 plan/path + 确认/驳回，无图形拖拽。
- Anthropic 协议下游：仅 OpenAI 风格。
- 后端管理面：不与 synth-loop 管理面集成，仅消费聊天/数据/闸 API。

---

## 本地联调

`mock-server/` 提供与 synth-loop 端点 1:1 的契约模拟，无真实后端时也能演练全部能力：

- 起服务：`cd mock-server && python main.py`（默认 `:13155`）。
- 预置数据：longdata（doc + memory）、相位 pipeline、artifact 产物。
- 契约测试：`python -m pytest test_mock.py`。
