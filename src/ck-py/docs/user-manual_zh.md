# context-kernel 使用手册

> 本手册面向 **context-kernel 的操作者 / Agent / 集成方**——你通过标准 OpenAI 入口驱动推理闸、在推模型前看清并修正上下文时，读这一份即可。
> 手册随 context-kernel 仓库分发。修订：2026-08-23。
> 本仓库是「推理闸机制」的独立自包含实现（Python，纯标准库 serve），协议部分与 phase-kernel（pk）一致（context_id 统一令牌、错误码闭集、双形态）。


---

## 零、概念速览

context-kernel（ck）是**推理闸机制**的独立实现：把「拼好发给模型的上下文」在推模型**之前**摊开，你可看、可改、可放过；改完再推，且**绝不把你的修正回写进会话**。

```
  用户消息 ──▶ 拼装内核 ──┬─ context_mode=layered ─▶ 六层拼装
                         └─ context_mode=passthrough ─▶ 通用态透传
              │
              ├─ closed ─▶ 直推 LLM ─▶ 答案
              └─ auto  ─▶ park（不推 LLM，生成 context_id）
                             │ 返 {context_id, context, gate:"pending"}
                             ▼
           开闸两段流（/chatgate/{context_id}）
             GET  ── 取回 content 视图（你来看）
             POST ── 你改完 ──▶ 只改 park 快照 ──▶ 推 LLM ─▶ 答案
                    （红线⑥：绝不回调 append_turn；unpark 一次性令牌）
```

| 名词 | 含义 |
|------|------|
| **推理闸（gate）** | 在「拼装完成」与「推模型」之间插入的可干预点；`closed` 关闸直推、`auto` 开闸先 park 给你看 |
| **拼装策略（context_mode）** | 与闸配置**正交**的第二维度：`layered`（六层拼装，默认）/ `passthrough`（通用态透传）。决定上下文「怎么来」；闸决定「看不看」 |
| **context_id** | 本次上下文的唯一令牌。closed 模式由 `metadata.session_id` 透传；auto 模式由 ck 瞬时所生成（uuid，不入库） |
| **park / peek / amend** | park=开闸暂存不推；peek=`GET /chatgate/{cid}` 看；amend=`POST /chatgate/{cid}` 改后推 |
| **六层拼装** | 会话（session_id / persona / doc）+ 客户端系统提示 + 临时滑动窗口 + 当前用户内容，按固定次序拼成 messages |
| **通用态（passthrough）** | 普通 OpenAI 请求 messages 原样透传，映射为单区域 `{"context": {次序: 内容}}`；可 POST 定向覆写任意 key，优化推理效果 |
| **两层 Session** | 永久区（persona/doc 等）+ 临时滑动窗口（deque maxlen=20，对齐 sl）；写权在 serve 层 |
| **标准入口（OpenAI 协议面）** | 对外只暴露 `POST /v1/chat/completions`（标准 OpenAI 协议 body）；closed 直推 / auto park；开闸两段流走 `/chatgate` 内部协议流（ck 不造 `tc-ck;run` 折叠指令，与 pk 本质差异见 design §1.2/§4.1） |
| **双形态** | 形态一独立 serve（`python -m context_kernel.serve.server`）；形态二组件集成（`from context_kernel import ContextKernel`） |
| **降级模式** | `degraded_mode` 由后端/模型可用性决定；机制仍推进但部分保证失效（当前 mock 闭环恒为 False） |

**关键设计**：`core/` 与 `ports/` 零外部依赖；所有 LLM / 数据面差异在 `adapters/`；拼装与闸分离各自生长（红线⑦：闸逻辑只写一份）；拼装策略（`context_mode`）与闸（`gate_mode`）正交、各自独立演化。

---

## 一、部署

### 1.1 Python 服务（独立部署形态，双形态·形态一）

```bash
# 默认：MockLlmProvider（自包含，零外部依赖，演示用）
python -m context_kernel.serve.server --port 8090
# 监听 0.0.0.0:8090

# 指定闸模式（closed 关闸直推 / auto 开闸先 park）
python -m context_kernel.serve.server --port 8090 --gate-mode auto

# 指定主模型名（演示用；接真实 LLM 时换成你的标识）
python -m context_kernel.serve.server --port 8090 --model ck-primary

# 指定拼装策略（layered 六层 / passthrough 通用态）
python -m context_kernel.serve.server --port 8090 --context-mode passthrough
```

### 1.2 组件集成形态（双形态·形态二）

```python
from context_kernel import ContextKernel
from context_kernel.adapters.mock_llm import MockLlmProvider

# 默认 layered（六层拼装）；显式开通用态可传 context_mode="passthrough"
kernel = ContextKernel(source, data_plane, MockLlmProvider("<reply>"),
                       "ck-primary", "ck-fallback")
result = kernel.run_openai({"messages":[{"role":"user","content":"hi"}],
                             "metadata":{"session_id":"x"}})
print(result.content)
```

> 形态一与形态二共用同一份 `core/context_kernel.py`，闸逻辑只写一份（红线⑦）。

### 1.3 验证（mock 闭环，不接真实 LLM）

```bash
python tests/run_all.py              # 统一回归：端口黑盒 + serve 冒烟（全绿）
python tests/test_serve_smoke.py     # serve HTTP 端点冒烟（黑盒）
python tests/test_ports_blackbox.py  # 三端口协议 + 红线⑥ 黑盒
```

---

## 二、使用

### 2.1 标准入口（OpenAI 协议面）：`POST /v1/chat/completions`

**关闸直推（closed，默认）**：

```bash
curl -X POST http://127.0.0.1:8090/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"你好"}],
       "metadata":{"session_id":"demo-1"}}'
```

响应（OpenAI 兼容 envelope）：

```json
{"context_id":"demo-1","content":"<mock reply>","result_ref":null,
 "ext":{"model":"ck-primary","usage":{"prompt_tokens":0,"completion_tokens":0,"total_tokens":0}}}
```

**开闸 park（auto）**：

```bash
curl -X POST http://127.0.0.1:8090/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"帮我写周报"}]}'
# → {"context_id":"<uuid>","context":{...区域结构...},"gate":"pending"}
```

### 2.2 开闸两段流（/chatgate/{context_id}）

| 动作 | 端点 | 含义 |
|------|------|------|
| peek（看） | `GET /chatgate/{context_id}` | 取回该次上下文视图（区域 + 次序） |
| amend（改后推） | `POST /chatgate/{context_id}` | 修正后只改 park 快照，推 LLM 出结果；unpark 一次性 |

```bash
# 看清上下文
curl http://127.0.0.1:8090/chatgate/<context_id>

# 改完再推（只改这次快照，不动会话）
curl -X POST http://127.0.0.1:8090/chatgate/<context_id> \
  -H "Content-Type: application/json" \
  -d '{"context":{"current_user_content":{"0":"帮我写一份 Q2 增长复盘周报"}}}'
# → {"context_id":"...","content":"<mock reply>","ext":{"gate":"auto"}}
```

> **一次性令牌**：`gate_set` 推完即 `unpark`，同一 `context_id` 再 `GET` 返回 `{"error":"unknown context_id"}`。要再改，重新发一条消息拿新 `context_id`。

### 2.3 服务端配置（集成方注意）

`gate_mode`（闸）与 `context_mode`（拼装策略）都是**服务端全局配置**，请求**无权控闸 / 无权改拼装策略**（design §1.3）。只能经 `/context-conf/` 读取或切换：

```bash
curl http://127.0.0.1:8090/context-conf/            # GET 读 {gate_mode, context_mode}
curl -X POST http://127.0.0.1:8090/context-conf/ \
  -H "Content-Type: application/json" -d '{"gate_mode":"auto"}'            # POST 改闸
curl -X POST http://127.0.0.1:8090/context-conf/ \
  -H "Content-Type: application/json" -d '{"context_mode":"passthrough"}'  # POST 改拼装策略
```

HTTP body / metadata **不携带** `gate_mode` / `context_mode`；它们由服务端 `GateConfig` 持有。两字段可独立读写，互不影响（正交）。

### 2.4 通用态（context_mode=passthrough）

普通 OpenAI 请求 `messages` **原样透传**，映射为单区域 `{"context": {次序: 内容}}`。开闸时看到全量消息，POST 可**定向覆写任意 key 的 content**，从而优化推理效果：

```bash
# 起服务：通用态 + 开闸
python -m context_kernel.serve.server --port 8090 --context-mode passthrough --gate-mode auto

# 发一条普通 OpenAI 请求（含 system + user）
curl -X POST http://127.0.0.1:8090/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"system","content":"你是助手"},{"role":"user","content":"你好"}]}'
# → {"context_id":"<uuid>","context":{"context":{"0":"你是助手","1":"你好"}},"gate":"pending"}

# 定向覆写第 0 条（system）后推
curl -X POST http://127.0.0.1:8090/chatgate/<context_id> \
  -H "Content-Type: application/json" \
  -d '{"context":{"context":{"0":"你是严谨的助手"}}}'
```

> **与六层的区别**：通用态不重排、不丢弃任何消息，`role` 保留在原文；覆写只改 content、不动 role。它面向「非六层风格」的任意 OpenAI 请求，且**只观测+干预+透传，绝不回写会话**（红线⑥）。

---

## 三、协议与信封

**标准入口 envelope（closed）** 对齐 OpenAI chat：

```json
{"context_id":"<str>","content":"<str>","result_ref":null,
 "ext":{"model":"<str>","usage":{...}|null}}
```

**开闸信封（auto park）**：

```json
{"context_id":"<str>","context":{...区域字典...},"gate":"pending"}
```

- `context_id`：本次上下文唯一令牌（closed 透传 session_id / auto 瞬时 uuid）。
- `content`：模型产出（closed 直推 / auto amend 后推）。
- `context`：park 时的区域结构 `{区域: {次序: 内容}}`，可经 `POST /chatgate/{cid}` 整体替换修正。六层（layered）下区域为 `session_id/persona/doc/client_system/temp/current`；通用态（passthrough）下区域固定为单区域 `context`。
- `ext`：`model` / `usage` / `gate`（auto 时标 `"auto"`）。

**错误码（闭集）**：

| 错误码 | 触发场景 |
|--------|---------|
| `unknown context_id` | `GET/POST /chatgate/{cid}` 的 cid 不存在或已 unpark |
| `missing context_id` | `/chatgate/` 路径缺 cid |
| `invalid gate_mode` | `POST /context-conf/` 传非法 `gate_mode` |
| `missing gate_mode` | `POST /context-conf/` 缺 `gate_mode` 字段 |
| `invalid context_mode` | `POST /context-conf/` 传非法 `context_mode`（非 layered/passthrough） |
| `missing context_mode` | `POST /context-conf/` 缺 `context_mode` 字段 |
| `not found` | 错误端点（非 `/v1/chat/completions` / `/chatgate/...` / `/context-conf/` / `/health` / `/schema`） |

**i18n**：当前 `context` 区域结构字段固定英语（六层：`session_id` / `persona` / `doc` / `client_system_messages` / `temp_sliding` / `current_user_content`；通用态：`context`）；messages 内容按请求语言。

---

## 四、配置

### 4.1 命令行参数（serve 门面）

| 参数 | 默认 | 说明 |
|------|------|------|
| `--port` | `8080` | 监听端口 |
| `--gate-mode` | `closed` | 服务端闸模式：`closed`（关闸直推）/ `auto`（开闸先 park） |
| `--context-mode` | `layered` | 服务端拼装策略：`layered`（六层拼装）/ `passthrough`（通用态透传） |
| `--model` | `ck-primary` | 主模型名（演示用；接真实 LLM 时换成你的标识） |

### 4.2 内核配置（代码注入）

| 项 | 默认 | 说明 |
|------|------|------|
| `primary_model` / `fallback_model` | `ck-primary` / `ck-fallback` | 主 / 备模型（design §4.5 模型级降级；fallback 当前为占位） |
| `gate_mode`（构造 / `set_gate_mode`） | `closed` | 闸模式运行时切换（对齐 `/context-conf/` 语义） |
| `context_mode`（构造 / `set_context_mode`） | `layered` | 拼装策略运行时切换（对齐 `/context-conf/` 语义；与 gate_mode 正交） |
| `SessionStore` 临时窗口 `maxlen` | `20` | 临时滑动窗口上限（对齐 sl） |
| `LlmProvider` | `MockLlmProvider` | 演示用；接真实 LLM 实现 `ports.LlmProvider` 注入 |
| `DataPlane` | `NoOpDataPlane` | 形态①纯 chat 无前序产物；接 rag/外部源实现 `ports.DataPlane` |

### 4.3 六层拼装（只读视图来源）

`SessionView` 由 `SessionStore.read_view()` 提供，按固定次序拼装（红线④写权在 serve 层，拼装只读）：

1. **session_id 层**：当前 session 标识
2. **persona 层**：永久区人设
3. **doc 层**：永久区文档/知识
4. **client_system_messages 层**：客户端系统提示（可选）
5. **temp_sliding 层**：临时滑动窗口（deque maxlen=20）
6. **current_user_content 层**：当前用户内容（末条 user）

### 4.4 通用态拼装（context_mode=passthrough）

`build_passthrough(messages)` 将普通 OpenAI 请求的 `messages` **原样透传**，不重排、不丢弃：

- 映射为单区域 `region_index = {"context": [0,1,...]}`，区域结构 `{"context": {次序: 内容}}`。
- `role` 保留在消息原文；闸覆写只改 content（对齐 `reassemble_from_custom` 语义）。
- 面向「非六层风格」的任意 OpenAI 请求；只观测 + 干预 + 透传，绝不回写会话（红线⑥）。

> **六层 vs 通用态**：六层是 sl 的定制拼装（ck 抽象出的组件将来挂 sl）；通用态是 ck 面向普通 OpenAI 请求的通用策略。两者经 `context_mode` 正交切换，默认 `layered` 保持兼容。

---

## 五、红线与安全

| # | 红线 | 操作者可见表现 |
|:---:|------|------|
| ① | 禁智能滑动 | 无自动记忆/相位状态机；临时窗口截断即丢（红线①） |
| ② | 拼装与闸分离各自生长 | `assemble.py` 与 `gate.py` 独立；闸逻辑单点（红线⑦） |
| ③ | `context_id` 统一令牌 | 标准入口/两段流共用同一 `context_id`；瞬时生成不入库 |
| ④ | 会话写权在 serve 层 | 拼装只经 `SessionView` 只读；`append_turn` 仅在 serve 层（core 零写权） |
| ⑤ | 闸逻辑单点 | `gate_get`/`gate_set` 只写一份于 `core/gate.py`；serve 仅转发，不复制（红线⑦） |
| ⑥ | 闸不回写会话 | `gate_set` 只改 park 内快照，**绝不回调 `append_turn`**；会话本身不动 |
| ⑦ | 协议闭集 / 零依赖 | core/ports/serve 仅标准库；错误码闭集，未知端点不静默放行 |

**兜底原则**：任何未预见失败走对应错误码（见 §三）；`context_id` 不存在即 `unknown context_id`；非法 `gate_mode` 即 `invalid gate_mode`，不静默放行。

---

## 附录

### A. 指令速查

| 形态 | 示例 |
|------|------|
| 关闸直推（closed） | `POST /v1/chat/completions` + `{messages, metadata.session_id}` |
| 开闸 park（auto） | `POST /v1/chat/completions`（gate_mode=auto）→ `{context_id, context, gate:pending}` |
| 通用态开闸 | `POST /v1/chat/completions`（context_mode=passthrough + gate_mode=auto）→ `{"context":{"context":{次序:内容}},"gate":"pending"}` |
| 看上下文 | `GET /chatgate/{context_id}` |
| 改后推 | `POST /chatgate/{context_id}` + `{context:{区域:{次序:内容}}}` |
| 读配置 | `GET /context-conf/` |
| 改闸配置 | `POST /context-conf/` + `{gate_mode:"auto"\|"closed"}` |
| 改拼装策略 | `POST /context-conf/` + `{context_mode:"layered"\|"passthrough"}` |
| 健康检查 | `GET /health` |
| 取 schema | `GET /schema` |

> **context 区域字典**：`POST /chatgate/{cid}` 的 `context` 为 `{区域: {次序: 内容}}`，可同时改多个区域（persona / doc / current_user_content 等）。区域名见 §四 4.3；通用态下区域固定为 `context`。

> **双形态**：形态一独立 serve（`python -m context_kernel.serve.server`）；形态二组件集成（`from context_kernel import ContextKernel` + 装配自己的 LlmProvider/DataPlane，集成方只改 import 不碰内核）。

### B. 错误码速查

| 错误码 | 含义 | 常见场景 |
|--------|------|---------|
| `unknown context_id` | cid 不存在 / 已 unpark | `GET/POST /chatgate/{cid}` 过时令牌 |
| `missing context_id` | 路径缺 cid | `/chatgate/` 空路径 |
| `invalid gate_mode` | 非法闸模式 | `POST /context-conf/` 传非 closed/auto |
| `missing gate_mode` | 缺字段 | `POST /context-conf/` 无 `gate_mode` |
| `invalid context_mode` | 非法拼装策略 | `POST /context-conf/` 传非 layered/passthrough |
| `missing context_mode` | 缺字段 | `POST /context-conf/` 无 `context_mode` |
| `not found` | 错误端点 | 非声明端点 |

### C. 端点 / 参数

| 项 | 说明 |
|------|------|
| `POST /v1/chat/completions` | 标准入口（closed 直推 / auto park） |
| `GET /chatgate/{context_id}` | 取回 content 视图 |
| `POST /chatgate/{context_id}` | 反向修正后推 LLM（unpark 一次性） |
| `GET /context-conf/` | 读服务端配置（`gate_mode` / `context_mode`） |
| `POST /context-conf/` | 改 `gate_mode` / `context_mode`（请求无权控闸 / 无权改策略） |
| `GET /health` | `{status, degraded_mode, gate_mode}` |
| `GET /schema` | 返回 `CK_SCHEMA`（messages 形态 / 闸协议 / outputs / directives） |
| `--port` / `--gate-mode` / `--context-mode` / `--model` | 见 §四 |

### D. 构建 / 验证命令

```bash
python tests/run_all.py              # 统一回归（mock 闭环，全绿）
python -m context_kernel.serve.server --port 8090 --gate-mode auto --context-mode passthrough   # 起服务（通用态 + 开闸）
```

> 数据模型 + 三端口协议 / 六层拼装内核 / **通用态（context_mode=passthrough）** /
> serve 关闸闭环 / 两层 Session / 推理闸两段流 / 可配置开闸与拼装策略（/context-conf/）/


