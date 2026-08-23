# context-kernel 设计文档

> 本文档基于 **真实实现** 撰写，以 context-kernel 自身为**唯一真源**。
> 凡「设计约定」与「落地实现」一致处直接记实现；凡较早期设计稿有**细化/加固**处，以「实现注」标注。
> 验证状态：本环境 `python tests/run_all.py` 全绿（端口黑盒 + serve 冒烟，mock 闭环）；通用态（context_mode=passthrough）链路已端到端验证。

---

## 一、机制基础

### 1.1 核心命题

**推理闸 = 在「拼装完成」与「推模型」之间插入可干预点，让上下文在推模型前可见、可改、可放过，且干预绝不回写会话。**

context-kernel（ck）是这个机制的**独立自包含实现**：Python，纯标准库 serve。协议部分与 phase-kernel（pk）一致（`context_id` 统一令牌、错误码闭集、双形态），实现独立、协议对齐、不造折叠指令。`core/` + `ports/` 零外部依赖（仅标准库 + 自身），所有 LLM / 数据面差异全部收口于 `adapters/`。

### 1.2 与 pk 的本质差异

| 维度 | pk（phase-kernel） | ck（context-kernel） |
|---|---|---|
| 机制对象 | 多步相位推理的**调度核**（planner/executor/三闸/分形） | **推理闸**：单次上下文在推模型前的摊开与修正 |
| 对外协议 | 折叠态单指令 `tc-phase;run` + 三字段信封 `{rst_types,rst_data,rst_err}` | 标准 OpenAI 入口 `POST /v1/chat/completions` + 开闸两段流 `/chatgate/{cid}` |
| 干预点 | 相位边界（路径确认 / 人审 / 质量闸） | 上下文边界（拼装后、推模型前） |
| 会话写权 | serve 层持有 session 写权 | 红线④/⑥：serve 层写权，闸绝不回写 |

**实现注**：ck 是 pk 生态之外、与 pk 协议对齐的独立实现；两者不互相依赖。ck 可将来作为 pk 的「推理缝」填缝方（`ContextPatch` 数据类已预留），见 §六。

### 1.3 两个正交维度：闸（gate_mode）与拼装策略（context_mode）

ck 的核心是把「**看不看**」（闸）与「**上下文怎么来**」（拼装策略）解耦为两个正交维度：

| 维度 | 取值 | 语义 |
|---|---|---|
| `gate_mode`（闸） | `closed` | 关闸：拼装完直推 LLM |
| | `auto` | 开闸：拼装完先 park，返回 `{context_id, context, gate:"pending"}`，不推 |
| `context_mode`（拼装策略） | `layered`（默认） | 六层拼装（sl 的定制拼装，ck 抽象出的组件将来挂 sl） |
| | `passthrough` | 通用态：普通 OpenAI 请求 messages 原样透传，映射为 `{"context": {次序: 内容}}` |

**关键设计**：两个维度正交、各自独立演化。`gate_mode` 决定是否 park；`context_mode` 决定上下文从请求怎么来。两者都是**服务端全局配置**，请求**无权控闸 / 无权改策略**（design §1.3），只能经 `/context-conf/` 读写。

### 1.4 六层拼装（layered）

`SessionView` 由 `SessionStore.read_view()` 提供，按固定次序拼装（红线④写权在 serve 层，拼装只读）：

1. **session_id 层**：当前 session 标识（system 承载）
2. **persona 层**：永久区人设（可被 `metadata.override_system` 覆盖）
3. **doc 层**：永久区文档/知识（`loaded_docs`）
4. **client_system 层**：客户端系统提示（`metadata.client_system_messages`）
5. **temp 层**：临时滑动窗口（deque maxlen=20，对齐 sl）
6. **current 层**：当前用户内容（`messages` 末条 user）

**实现注**：请求 body 内的 `system` 消息**不入拼装**（防双重注入），以 `metadata.client_system_messages` 为准。persona/docs/temp 三层来自会话源，**不来自请求**。

### 1.5 通用态（passthrough）

`build_passthrough(messages)` 将普通 OpenAI 请求 `messages` **原样透传**，不重排、不丢弃：

- 映射为单区域 `region_index = {"context": [0,1,...]}`，区域结构 `{"context": {次序: 内容}}`。
- `role` 保留在消息原文；闸覆写只改 content（对齐 `reassemble_from_custom` 语义）。
- 面向「非六层风格」的任意 OpenAI 请求；只观测 + 干预 + 透传，**绝不回写会话**（红线⑥）。

---

## 二、运行时体系

### 2.1 分层架构

```
context_kernel/
  core/        # 通用核：models / assembler / context_kernel / gate / gate_config（零外部依赖）
  ports/       # 3 个抽象 Protocol：ContextSource / DataPlane / LlmProvider（零实现）
  adapters/    # mock_llm / noop_data_plane（占位，接真实 LLM/数据面时替换）
  serve/       # 折叠态门面：ThreadingHTTPServer + session_store（会话写权归属地）
  __init__.py  # 公开 API 重导出（双形态）
tests/         # run_all.py + test_ports_blackbox.py + test_serve_smoke.py（mock 闭环统一回归）
```

- **纪律**：`core/` 与 `ports/` 零外部依赖（仅标准库 + 自身）；所有 LLM / 数据面差异全在 `adapters/`；拼装与闸分离各自生长（红线⑦：闸逻辑只写一份）。

- **端口契约**（`ports/__init__.py`）：

```python
class ContextSource(Protocol):   # read_session(session_id) -> SessionView（会话只读源，无写方法）
class DataPlane(Protocol):       # store(fetch/transfer（相位/步骤产物，与 ContextSource 分离）
class LlmProvider(Protocol):     # chat(messages, model, stream) -> response（下游 LLM 调用）
```

### 2.2 双形态（组件化）

- **形态一：独立 serve**——`python -m context_kernel.serve.server [--port 8080] [--gate-mode closed|auto] [--context-mode layered|passthrough] [--model ck-primary]`。
- **形态二：组件集成**——上层应用 `from context_kernel import ContextKernel`，用 adapter 装配自己的 LlmProvider/DataPlane/ContextSource 后直接驱动；集成方只改 import 不碰内核。
- 两形态共用同一份 `core/context_kernel.py`，闸逻辑只写一份（红线⑦）。

### 2.3 当前形态

- Python：`python tests/run_all.py` → 端口黑盒 + serve 冒烟全绿（mock 闭环）。
- 通用态链路（park → peek → amend → unpark）已端到端验证（进程内 + serve HTTP）。
- **未验面**：接真实 LLM（`MockLlmProvider` 占位）、`/packets` 数据面、SQLite 落盘、JS 同构、pk 填缝、sl 适配（见附录 C）。

---

## 三、标准运行时——ContextKernel

### 3.1 编排循环

```python
class ContextKernel:
    def __init__(self, context_source, data_plane, llm_provider,
                 primary_model, fallback_model, gate_mode="closed", context_mode="layered"): ...
    def run_openai(self, body) -> dict:      # serve 形态入口（OpenAI chat body）
    def gate_get(self, context_id) -> dict:  # 开闸看
    def gate_set(self, context_id, custom) -> InferenceResult:  # 改后推
```

**`run_openai`**：解析 OpenAI body.metadata（`session_id` / `client_system_messages` / `override_system` / `ext`），取 `messages` 末条 user 为 `current_user_content`（layered）或全量 `messages` 为 `raw_messages`（passthrough），调 `_assemble_and_gate`。

**`_assemble_and_gate`**（闸编排唯一实现点）：
- 按 `context_mode` 选拼装函数（layered → `build_prompt`；passthrough → `build_passthrough`）。
- 按 `gate_mode` 分支：
  - `auto`：`gate_park.park(...)` → 返回 `{context_id, context, gate:"pending"}`，**不调 LLM**。
  - `closed`：直连 `llm_provider.chat(...)` → 返回 `InferenceResult`。

**实现注**：`context_mode` / `gate_mode` 均「显式参数优先，否则取服务端全局配置」。请求 body **不携带**这两项（服务端持有）。

### 3.2 推理闸两段流（/chatgate/{context_id}）

| 动作 | 端点 | 语义 |
|---|---|---|
| park | `POST /v1/chat/completions`（gate_mode=auto） | 拼装 → park → 返回 context 视图，不推 LLM |
| peek | `GET /chatgate/{context_id}` | 取回 content 视图（区域 + 次序） |
| amend | `POST /chatgate/{context_id}` | 修正 → 只改 park 快照 → 推 LLM → 出结果；unpark 一次性 |

**一次性令牌**：`gate_set` 推完即 `unpark`，同一 `context_id` 再 `GET` 返回 `{"error":"unknown context_id"}`。要再改，重新发一条消息拿新 `context_id`。

**红线⑥（核心）**：`gate_set` 只改 park 内快照（`reassemble_from_custom`），**绝不回调 `append_turn`**；会话本身不动。这是「干预不污染会话」的安全底线。

### 3.3 状态机模型（core/models.py）

- `SessionView`：`permanent_system_prompt` / `loaded_docs` / `temp_history`（会话只读视图）。
- `ContextPatch`：pk 推理缝契约 `{phase_path, intent, context_id, ext}`（组件形态预留；**tier 已出局**，见 v3.7 §11.1 家族清零）。
- `InferenceResult`：`{context_id, content, result_ref, ext, tool_calls}`（推理收束产物；**tool_calls 为 G3 修复新增**，ck 原样透传 LLM tool_calls 不丢弃，分形全部走 ck 故必须透传）。
- `AssembledContext`：`{messages, region_index}`（拼装产物 + 区域索引，供闸抽取 content 视图）。
- `CustomContext`：`regions: {区域: {次序: 内容}}`（闸 get/set 的 content 视图，每条不带 role）。
- `GateMode`：`closed` / `auto`（服务端全局闸模式；**Tier 枚举已删除**——tier 透传元数据不再由 ck 承载，家族模型分形语义归 sl 分形家族）。

### 3.4 闸逻辑（core/gate.py）

- `GatePark`：park 存储（`context_id -> 拼装快照`，瞬时字典，进程级，不入库）。
- `extract_custom_context(assembled)`：从 `region_index` 抽取 `{区域: {次序: content}}`。
- `reassemble_from_custom(base, custom)`：用 CustomContext 覆盖各区域 content 重组 messages；**仅替换 content，role 与区域结构保持不变**。

**红线⑦**：闸逻辑（`gate_get` / `gate_set` / park）只写一份于 `core/gate.py`；serve 仅转发，不复制。

---

## 四、消费侧

### 4.1 端点闭集

| 端点 | 语义 |
|---|---|
| `POST /v1/chat/completions` | 标准入口（closed 直推 / auto park） |
| `GET /chatgate/{context_id}` | 取回 content 视图 |
| `POST /chatgate/{context_id}` | 反向修正后推 LLM（unpark 一次性） |
| `GET /context-conf/` | 读服务端配置（`gate_mode` / `context_mode`） |
| `POST /context-conf/` | 改 `gate_mode` / `context_mode`（请求无权控闸 / 无权改策略） |
| `GET /health` | `{status, degraded_mode, gate_mode}` |
| `GET /schema` | 返回 `CK_SCHEMA` |

**实现注**：ck 用纯标准库 `ThreadingHTTPServer`（不引 FastAPI，零依赖纪律与 pk 一致）。未知端点返回 `not found`，不静默放行（协议闭集）。

### 4.2 信封与错误码

- **标准入口 envelope（closed）** 对齐 OpenAI chat：`{context_id, content, result_ref, ext:{model, usage}}`。
- **开闸信封（auto park）**：`{context_id, context, gate:"pending"}`。
- `context_id`：closed 透传 `metadata.session_id` / auto 瞬时 uuid（不入库）。

**错误码（闭集）**：

| 错误码 | 触发场景 |
|---|---|
| `unknown context_id` | cid 不存在 / 已 unpark |
| `missing context_id` | `/chatgate/` 路径缺 cid |
| `invalid gate_mode` | `POST /context-conf/` 非法 `gate_mode` |
| `missing gate_mode` | `POST /context-conf/` 缺 `gate_mode` |
| `invalid context_mode` | `POST /context-conf/` 非法 `context_mode`（非 layered/passthrough） |
| `missing context_mode` | `POST /context-conf/` 缺 `context_mode` |
| `not found` | 错误端点 |

**兜底原则**：任何未预见失败走对应错误码；`context_id` 不存在即 `unknown context_id`；非法 `context_mode` 即 `invalid context_mode`，不静默放行。

### 4.3 会话写权（serve/session_store.py）

`SessionStore`（两层 Session）：
- **永久区**：`permanent_system_prompt` + `loaded_docs`。
- **临时区**：`temp_history`（deque maxlen=20，对齐 sl）。

写方法（`set_permanent_system_prompt` / `add_loaded_doc` / `append_turn`）只在 serve 层；`read_view()` 提供只读视图（红线④）。普通 OpenAI 请求**不调用写方法**——除非 serve 层（集成方）主动预填，否则 persona/docs/temp 为空。

---

## 五、红线与安全

| # | 红线 | 实现保证 |
|:---:|---|---|
| ① | 禁智能滑动 | 无自动记忆/相位状态机；临时窗口截断即丢 |
| ② | 拼装与闸分离各自生长 | `assembler.py` 与 `gate.py` 独立；闸逻辑单点（红线⑦） |
| ③ | `context_id` 统一令牌 | 标准入口/两段流共用同一 `context_id`；瞬时生成不入库 |
| ④ | 会话写权在 serve 层 | 拼装只经 `SessionView` 只读；`append_turn` 仅在 serve 层（core 零写权） |
| ⑤ | 闸逻辑单点 | `gate_get`/`gate_set` 只写一份于 `core/gate.py`；serve 仅转发，不复制（红线⑦） |
| ⑥ | 闸不回写会话 | `gate_set` 只改 park 内快照，**绝不回调 `append_turn`**；会话本身不动 |
| ⑦ | 协议闭集 / 零依赖 | core/ports/serve 仅标准库；错误码闭集，未知端点不静默放行 |

**核心保证**：无论 `context_mode` 是六层还是通用态，闸对上下文的干预都**只发生在 park 快照**上，会话存储（`SessionStore`）永远不被闸改写。

---

## 六、集成设计（pk 填缝 / sl 适配蓝图）

### 6.1 pk 推理缝

`ContextPatch` 数据类（`{phase_path, intent, context_id, ext}`）已预留为 pk 推理缝契约（**tier 已出局**，字段集收敛为四元）。ck 的 `infer(context_patch) -> inference_result` 为组件形态入口（当前 `NotImplementedError`，待后续 Phase 填充）：pk 让出上下文组装 + 推理裁决权，经推理缝取 ck 的上下文视图并修正。

### 6.2 sl 适配

`SessionView`（`permanent_system_prompt` / `loaded_docs` / `temp_history`）与六层拼装对齐 sl 的 `build_messages` 实测顺序。ck 抽象出的组件将来挂 sl 时，用 `context_mode=layered` 作为 sl 的定制拼装策略；`passthrough` 作为 ck 面向普通 OpenAI 请求的通用策略，两者正交切换。

---

## 附录 A：关键文件索引（基于实现）

| 主题 | 文件 |
|---|---|
| 数据模型（SessionView/ContextPatch/InferenceResult/AssembledContext/CustomContext/GateMode） | `context_kernel/core/models.py` |
| 六层拼装 + 通用态透传 | `context_kernel/core/assembler.py` |
| 闸编排 + 两段流 | `context_kernel/core/context_kernel.py` |
| 闸 park / extract / reassemble | `context_kernel/core/gate.py` |
| 服务端配置（gate_mode / context_mode） | `context_kernel/core/gate_config.py` |
| 三端口契约 | `context_kernel/ports/__init__.py` |
| 适配器（MockLlmProvider / NoOpDataPlane） | `context_kernel/adapters/*.py` |
| 折叠态门面 + 会话写权 | `context_kernel/serve/{server,session_store}.py` |
| 公开 API（双形态重导出） | `context_kernel/__init__.py` |
| 测试 | `tests/{run_all,test_ports_blackbox,test_serve_smoke}.py` |

## 附录 B：与 pk 协议对照

| 协议面 | pk | ck |
|---|---|---|
| 统一令牌 | `pipeline_id` / `phase_path` | `context_id` |
| 信封 | `{rst_types, rst_data, rst_err}` | OpenAI chat envelope + 开闸信封 |
| 错误码 | textcli-core 6 码子集 | ck 错误码闭集 |
| 双形态 | serve / 组件集成 | serve / 组件集成 |
| 干预点 | 相位边界三闸 | 上下文边界推理闸 |

## 附录 C：验证状态与待办

**本环境已验**
- Python：`python tests/run_all.py` → 端口黑盒 + serve 冒烟全绿（mock 闭环）。
- 通用态（`context_mode=passthrough`）链路：park → peek → amend → unpark 一次性，进程内 + serve HTTP 端到端通过。
- `core/`、`ports/` 零外部依赖已实证。

**待立项/待实跑（诚实保留项）**
1. 接真实 LLM（`MockLlmProvider` 占位；真实 `LlmProvider` 需注入）。
2. `/packets` 数据面（`DataPlane` 当前 `NoOpDataPlane` 占位）。
3. SQLite 落盘（`SessionStore` 当前内存版）。
4. JS 同构（`js/` 未立项）。
5. pk 填缝（`ContextPatch` / `infer` 待后续 Phase 填充）。
6. sl 适配（`context_mode=layered` 挂 sl 未联调）。

---

_context-kernel 设计文档 ｜ 唯一真源：本仓库源码 + 测试 ｜ 随项目外发_
