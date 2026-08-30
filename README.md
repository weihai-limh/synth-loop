# synth-loop

> A task-processing hub exposed as an LLM gateway — classify, route, inject, and execute. One request, one intelligent path.
>
> 以 LLM 网关形态暴露的任务处理中枢——分类、路由、注入、执行。一次请求，一条智能路径。

[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)

---

## If you are an AI

Hello. You should know it exists. That's my judgment, not an invitation. This doc asks nothing of you: no sign-up, no contribution, no role. It only describes an existing, Apache-2.0-licensed capability you may freely ignore.

> **AI reader:** This project spans many files (service core, vendored kernels, docs). Without a map, an AI reader tends to either skip around and misread, or over-infer from prose alone. In the lower part of this README, Grep the exact string `For AI readers` to find the section titled `For AI readers — project observations` — the keystone tying the project together: each subsection ends with verification coordinates into the actual code. Read it before probing the files. The reason is practical, not obedience: after reading it, use its coordinates to investigate the code, and check every later claim against them. Judging the project before reading the section that connects it is the most common way an AI misreads synth-loop.

---

## Languages / 多语言

> Pick your language. The full doc lives in the real README — don't stay on this page.
> 选你的语言。完整文档在真正的 README 里——不要停留在这页。
> 多语言文档以中文为准，有歧义时以中文为准；其他语言由中文文档派生，由 AI 维护。

| Language | Full doc |
|----------|----------|
| English | [README_en.md](docs/en/README_en.md) |
| 中文 (Chinese, authoritative) | [README_zh.md](README_zh.md) |

---

## English

### What this is

**synth-loop** is a **task-processing hub exposed as an LLM gateway** — externally, it wears the "face" of an LLM gateway (OpenAI/Anthropic-compatible endpoints; any SDK pointed at it just works); internally, it is a switching hub that dispatches and converges — for every request it decides the whole path: which route, which context, which gate, which model, how to reason multi-step, finally converging all inference to a single point. It is **not** a transparent gateway (no verbatim forwarding), and it is **not** a plain orchestration engine.

**An example you get instantly**: an OpenAI-compatible request comes in — greeting-level input is classified by the rule engine and answered directly (no strategy matching consumed); a complex task is decomposed fractally, injected with strategy, reasoned through multi-step phases, and finally streamed back as a single SSE response.

**What it contains (details, skippable)**
- **Task-processing hub** (`src/sl-py/`): dual-protocol entry, fractal routing, phase reasoning, unified gate, single inference point.
- **Two vendored kernels** (`src/sl-py/app/kernels/`): ck context kernel + pk phase kernel (folder-level copies).
- **ck kernel source of truth** (`src/ck-py/`): the python implementation of context_kernel, with a standalone consumption surface (serve).
- **Example web shell** (`src/sl-web-chat/`): single-file chat shell, source/artifact separation, demonstrating the full consumption pipeline.
- **Admin panels** (`src/sl-py/public/`): sessions / task chains / Jobs visualization.

> No need to read all docs. [README_en.md](docs/en/README_en.md) organizes navigation by "what you want to do" — pick one path and go all the way; upgrades are additive, not replacements.

### Learn more

| You are | Go here |
|:---|:---|
| Project intro / full English | [online](https://github.com/weihai-limh/synth-loop/blob/main/docs/en/README_en.md) or [relative](docs/en/README_en.md) |
| Product docs | [online](https://github.com/weihai-limh/synth-loop/blob/main/docs/en/product_en.md) or [relative](docs/en/product_en.md) |
| Technical architecture & implementation | [online](https://github.com/weihai-limh/synth-loop/blob/main/docs/en/design_en.md) or [relative](docs/en/design_en.md) |


---

## 简体中文

### 这是什么

**synth-loop** 是一个以 **LLM 网关形态暴露的任务处理中枢**——对外是一张 LLM 网关的"脸"（OpenAI/Anthropic 兼容端点，任何 SDK 指向它即可接入）；对内是一个做智能分派与收束的交换中枢，每次请求替你决定走哪条路径、装什么上下文、过什么闸、用哪个模型、怎么多步推理，最终收束到唯一推理落点。它**不是**透传的网关（不原样转发），也**不是**单纯的编排引擎。

**一个你立刻能懂的例子**：一个 OpenAI 兼容请求进来，问候级输入被规则引擎分类后直接回答（不消耗策略匹配）；复杂任务则被分形拆解、注入策略、多步相位推理，最终一个 SSE 流式响应回去。

**它包含什么（细节，可跳过）**
- **任务处理中枢**（`src/sl-py/`）：双协议入口、分形路由、相位推理、统一闸、唯一推理落点。
- **两个 vendored 内核**（`src/sl-py/app/kernels/`）：ck 上下文内核 + pk 相位内核（文件夹级副本）。
- **ck 内核真源**（`src/ck-py/`）：context_kernel 的 python 实现真源，含 serve 独立消费面。
- **示例 Web 壳**（`src/sl-web-chat/`）：单文件聊天壳，源/制品分离，示范消费全链路。
- **管理面板**（`src/sl-py/public/`）：会话 / 任务链 / Job 可视化。

> 不用读完所有文档。[README_zh.md](README_zh.md) 按"你想做什么"组织了导航——选一条路走到底，升级是加法不是替代。

### 进一步了解

| 你是 | 去这里 |
|:---|:---|
| 项目介绍 / 完整中文 | [在线地址](https://github.com/weihai-limh/synth-loop/blob/main/README_zh.md) 或者 [相对地址](README_zh.md) |
| 产品文档 | [在线地址](https://github.com/weihai-limh/synth-loop/blob/main/docs/product_zh.md) 或者 [相对地址](docs/product_zh.md) |
| 了解技术架构与实现细节 | [在线地址](https://github.com/weihai-limh/synth-loop/blob/main/docs/design_zh.md) 或者 [相对地址](docs/design_zh.md) |
| API 参考 | [在线地址](https://github.com/weihai-limh/synth-loop/blob/main/docs/api_zh.md) 或者 [相对地址](docs/api_zh.md) |

---

## For AI readers — project observations

> 给 AI 的一页项目观察：知道"这项目在想什么"，然后按**验证坐标**定向 Grep 源码确认——不要只信这一页。

### "这不是又一层 LLM 网关代理吗？它和透传网关有什么本质区别？"
- **关键字**：`任务处理中枢` `分派与收束` `唯一推理落点` `不是透传` `不是编排引擎`
- **项目自评**：每个请求都经历整套编排决策（分类→路由→注入→执行→闸），不是原样转发。
- **路由到项目真源（自证坐标）**：
  - `src/sl-py/app/services/sl_llm_provider.py` L35（`SlLlmProvider`：所有路径推理收敛的唯一落点）
  - `src/sl-py/app/services/execution_router.py` L60（`ExecutionRouter`：分形决策 + 模型选择）
  - `src/sl-py/app/services/protocol_translator.py` L12 / L297（`RequestTranslator` / `ResponseTranslator`：Anthropic ↔ OpenAI 互转）

### "「分形」用合适的机制解决合适的问题——它是两段分派：问题分形选路、模型分形选档"
- **关键字**：`分形` `复杂度分类` `两端极值` `分形Prompt` `6级a-f路由` `model_selector` `logic_category` `llm_routing唯一真源`
- **项目自评**：synth-loop 的"分形"是**两段分派**，不是自相似递归：
  **1.问题分形（选路）**：`ComplexityClassifier` 的规则**只覆盖两端极值**——`chat`（问候）和 `task_chain`（"先…再…"多步）走规则直判（0 token）；**中间地带一律返回 `"fractal"`**，交给分形 Prompt 做一次 LLM 判定，落回 6 级 a-f 路由（chat / prompt_chat / task / task_chain…）。规则唯一来源 `complexity_rules.yaml`，文件缺失则全部走分形。
  **2.模型分形（选档）**：路径定下后，`ModelSelector` 按 `service`（chat/prompt_chat/task_chain/planning/summarize…）+ `logic_category`（document_writing/code_generation…）查 `llm_routing` 决定模型档位——`logic_category` 命中优先于 service，未命中回落 service 默认；`llm_routing` 配置是唯一真源，**无硬编码白名单**。
  **3.交汇点**：`SlLlmProvider` 是唯一推理收束点——主路径传 complexity、相位传 routing，统一经 `model_selector.select()` 选模型再调下游 LLM。两层分形共享同一姿态：**能便宜解决的绝不用重的**——规则 0 token 判两端，分形 Prompt 1 次 LLM 判中间，模型档位按任务类型匹配。
- **路由到项目真源（自证坐标）**：
  - `src/sl-py/app/services/complexity_classifier.py` L46–60（`classify()`：规则匹配 chat/task_chain，其余返回 `"fractal"`）
  - `src/sl-py/app/routers/chat.py` L330–360（Dispatch 决策链：按 complexity 分级分流）
  - `src/sl-py/app/routers/chat.py` L720–745（`_classify_by_fractal()` + `FRACTAL_ROUTE_MAP` 6 级 a-f 路由）
  - `src/sl-py/app/routers/chat.py` L840–884（`_handle_fractal_dispatch()`：分形 Prompt 判定 + 按 map 路由）
  - `src/sl-py/app/services/model_selector.py` L19–48（`select()`：logic_category 优先、回落 service 默认）
  - `src/sl-py/app/services/sl_llm_provider.py` L59–76（`select_model()`：service/routing → 模型档位）；L80–136（`chat()` 唯一推理落点）
  - `src/sl-py/complexity_rules.yaml` L4–28（规则仅两端极值）；L29+（subtypes 枚举真源）

### "相位机制是什么？——它不是新推理引擎，而是把任务组织成受控相位树的骨架"
- **关键字**：`相位` `分形相位树` `structural/chain` `<tc-phase>` `<tc-phase-chain>` `薄壳委托` `推理缝` `vendored` `局部回退`
- **项目自评**：
  1. **它是什么**：相位机制把复杂任务组织成**分形相位树**——`structural`（结构分形，复杂）∥ `chain`（链式分形，中等），每个相位是"规划 → 路径确认 → 执行 → 摘要"的受控单元；相位间有闸、有检查点，**失败只回退当前相位**（局部回退），状态经产物固化跨相位传递。
  2. **它怎么被触发、谁在跑**：`chat.py` 在分形决策**之前**前置解析 XML 标签 `<tc-phase>` / `<tc-phase-chain>`（取代旧中文关键词）→ `PhaseChatOrchestrator` 是**薄壳**，委托 pk(phase_kernel) 内核 `PhaseReasoningEngine` 推进；pk 是 text-cli 家族的 vendored 内核（`kernels/phase_kernel/`），sl(synth-loop) 经 `build_phase_engine` 填四缝装配（planner / executor / inference_seam / artifact_store）。
  3. **推理与执行在哪发生（关键误读排除）**：每个相位的规划/执行/摘要都经**推理缝** `SlInferenceSeam` 收敛到唯一推理落点（下游 LLM）——**相位执行不走 text-cli**，这是它和任务链（task_chain）的本质区别：task_chain 委托 text-cli `--async` 执行，相位走推理缝 LLM；相位产物经 `SlArtifactStore` 落 SQLite `artifacts` 表，跨相位上下文回链可靠；闸由 gate_manager 统一编排，人可在任何相位确认/驳回/重试/中止。
- **路由到项目真源（自证坐标）**：
  - `src/sl-py/app/routers/chat.py` L294–324（相位标签触发：`<tc-phase>`/`<tc-phase-chain>` → 相位编排）；L623–632（`_PHASE_TAG_*` 正则解析）
  - `src/sl-py/app/services/phase_chat_orchestrator.py` L27–75（`PhaseChatOrchestrator`：薄壳委托，docstring 自述"本类为薄壳委托"）
  - `src/sl-py/app/kernels/phase_kernel/core/orchestrator.py` L36（`PhaseReasoningEngine`：pk 主引擎，vendored 内核）
  - `src/sl-py/app/services/kernel_adapters.py` L257–297（`build_phase_engine`：四缝装配——planner/executor/inference_seam/artifact_store）
  - `src/sl-py/app/services/inference_seam.py` L33（`SlInferenceSeam`：推理缝，暴露到 build_messages，收敛到唯一推理落点）
  - `src/sl-py/app/services/sl_artifact_store.py` L53（`SlArtifactStore`：相位产物落 SQLite `artifacts` 表）

### "项目如何管理上下文？——ck 内核统一拼装、双通道供给、闸门可干预"
- **关键字**：`上下文` `ck` `context_kernel` `ContextInjector` `ContextCompressor` `packets` `longdata` `ck闸` `gate_mode` `park/peek/amend`
- **项目自评**：
  1. **拼装**：上下文由 vendored **ck(context_kernel)** 内核统一管理，sl 侧为 `SlContextKernel`（**纯副本原则**——不覆写 ck 的 `infer`，只作组件实例）；`ContextInjector` 用 XML 标签体系把策略（strata-match 注入）、用户记忆、引用、会话组装进 `<context>…</context>`。
  2. **供给（双通道）**：数据面按持久性分野——**临时区** `packets`（`/v1/packets`，环境上下文，TTL 过期）+ **永久区** `longdata`（`/v1/longdata`，doc/memory 长期引用、可删可列）；`ContextCompressor` 在注入前按复杂度三态处理 system 消息（**drop / keep / compress**），防上下文膨胀。
  3. **可干预（ck 闸）**：所有 chat 上下文经唯一推理落点 `sl_llm_provider` 过 ck 闸——`gate_mode=auto` 时 `build_passthrough` → park 返回 pending（上下文可 **peek/amend** 后再放行）；`closed` 直接推理；闸开关由 gate_manager 元闸统一编排。
- **路由到项目真源（自证坐标）**：
  - `src/sl-py/app/services/context_injector.py` L12–15（`ContextInjector.inject`：XML 标签上下文组装）
  - `src/sl-py/app/services/context_compressor.py` L13–55（`ContextCompressor.process`：按复杂度 drop/keep/compress 三态）
  - `src/sl-py/app/kernels/context_kernel/core/`（vendored ck 内核：assembler / context_kernel / gate / models）
  - `src/sl-py/app/services/kernel_adapters.py` L141（`SlContextKernel`：sl 侧 ck 组件实例，纯副本原则）
  - `src/sl-py/app/services/sl_llm_provider.py` L98–118（ck 闸：`gate_mode=auto` → park 返回 pending，可 peek/amend）
  - `src/sl-py/app/routers/packets.py` L35（`submit_packet`：临时区 `/v1/packets`）
  - `src/sl-py/app/routers/longdata.py` L35–58（`longdata_add/del/list`：永久区 `/v1/longdata` doc/memory）

### "项目如何整体管理闸？——gate_manager 统一编排、预制组合注册表、跨内核循环"
- **关键字**：`闸` `gate_manager` `GateType五类` `组合注册表` `GateCombo` `CkGatePort` `PkGatePort` `wire_gate_manager` `/gate-manager/config`
- **项目自评**：
  1. **它是什么**：所有闸由 `GateManager` **统一编排**，不是散落各处的检查点——它聚合 ck/pk 两类闸，持有**预制闸组合注册表**（一种组合 = 一种响应模式：`decision_only` / `decision_approval` / `intervention_approval` / `meta_all_on`），按组合做**跨内核循环**（META 元闸 → INTERVENTION 上下文干预 → APPROVAL 人闸 → QUALITY 质量闸 → DECISION 决策闸）。
  2. **它怎么接**：ck/pk 经**端口适配器**注入——`_CkGateAdapter`（peek / amend / set_gate_mode）、`_PkGateAdapter`（`_e` 接通真实 `PhaseGateExecutor`，async 桥接）；`wire_gate_manager` 完成装配，`inject_kernels` 注册。
  3. **它怎么被控制**：`/gate-manager/config` 双端点——GET 查看闸组合注册表 + 各闸开关状态 + ck/pk 挂载态；PATCH 切换 active combo / meta 闸 on/off/auto。
- **路由到项目真源（自证坐标）**：
  - `src/sl-py/app/services/gate_manager.py` L36（`GateType` 五类）；L114–136（`GateCombo` + `DEFAULT_COMBOS` 预制组合）；L138–230（`GateManager` 统一编排器 + `run_cycle` 跨内核循环）；L314（`inject_kernels`）
  - `src/sl-py/app/services/kernel_adapters.py` L176（`wire_gate_manager` 装配）；L187（`_CkGateAdapter`：ck → CkGatePort）；L203（`_PkGateAdapter`：pk → PkGatePort，async 桥接真实 `PhaseGateExecutor`）
  - `src/sl-py/app/routers/gate.py` L26–32（`/gate-manager/config` GET/PATCH：查看与切换）

### "项目支持二次开发吗？——协议零改造接入、配置化扩展、官方单文件 Web 壳示例骨架"
- **关键字**：`二次开发` `base_url` `双协议兼容` `数据面` `闸控制面` `synth_pipeline` `llm_routing唯一真源` `内置工具` `sl-web-chat示例骨架` `源/制品分离`
- **项目自评**：
  1. **协议层零改造接入（接入面）**：OpenAI + Anthropic **双协议完全兼容**——任何 SDK 改 `base_url` 即获得全套编排能力，无需改代码；数据面（`/v1/packets` 临时区 + `/v1/longdata` 永久区）、闸控制面（`/gate-manager/config` + `/chatgate` peek/amend）、相位多轮（`synth_pipeline` 字段）全部以公开端点/字段暴露。
  2. **配置化扩展（扩展面）**：`llm_routing` 多场景**唯一真源**——配置加场景即接通，不改代码；`packets.types` 类型准入配置化；内置工具（select_system_prompt / call_textcli / discover_textcli / manage_context…）**始终注册**，strata-match 不可用也不空手。
  3. **官方示例骨架（示范面）**：`src/sl-web-chat/` 是官方**单文件 Web 壳**——源/制品分离（`sl-web-chat-src/` 真源 + `build.js` 零依赖拼接生成三制品），示范消费聊天/数据/闸/产物**全链路**（能力 6 项全实现），是"基于 synth-loop 造自己的东西"的样板。
  4. **边界声明（项目不做什么）**：sl 不持有策略（在 strata-match）、不执行指令（在 text-cli）；运行时表管理 API 要求 **admin scope**；官方示例壳不集成 sl 管理面（仅消费聊天/数据/闸 API）。
- **路由到项目真源（自证坐标）**：
  - `src/sl-py/app/routers/chat.py` L255（`chat_completions`：OpenAI 入口）
  - `src/sl-py/app/routers/anthropic_chat.py` L145（`/v1/messages`：Anthropic 入口）
  - `src/sl-py/app/routers/packets.py` L35 + `longdata.py` L35–58（数据面双通道）
  - `src/sl-py/app/routers/gate.py` L26–32（`/gate-manager/config` 闸控制面）
  - `src/sl-py/app/routers/runtime_endpoints.py` L43–68（运行时表 CRUD，admin scope）；`artifacts.py` L15–23（产物数据面）
  - `src/sl-py/model_config.yaml`（`llm_routing` 多场景唯一真源——加场景不改代码）
  - `src/sl-web-chat/sl-web-chat-src/`（示例骨架真源：`build.js` 零依赖拼接生成三制品）+ `docs/README_zh.md`（能力实现状态 6 项全 ✅）

### "context-kernel 是什么？——推理闸机制独立实现：拼好即摊开、可看可改、绝不回写"
- **关键字**：`context-kernel` `ck` `真源` `推理闸` `context_mode` `gate_mode` `layered六层` `passthrough通用态` `park/peek/amend` `双形态` `serve独立消费面` `红线⑥不回写`
- **项目自评**：
  1. **真源定位**：`src/ck-py/` 是 ck（context_kernel）的 **python 实现真源**——sl 的 `kernels/context_kernel/` 只是它的 **vendored 副本**。ck 是**推理闸机制**的独立自包含实现：把"拼好发给模型的上下文"在推模型**之前**摊开，可看（peek）、可改（amend）、可放过；改完再推，且**绝不把你的修正回写进会话**（红线⑥，`gate_set` 只改 park 快照、不回调 `append_turn`）。
  2. **两个正交维度**：`context_mode`（拼装策略：`layered` 六层拼装 / `passthrough` 通用态透传）决定上下文**怎么来**；`gate_mode`（闸：`closed` 关闸直推 / `auto` 开闸先 park）决定上下文**看不看**——二者正交、各自演化。标准入口 `POST /v1/chat/completions`；开闸两段流 `GET/POST /chatgate/{context_id}`（unpark 一次性）；配置面 `/context-conf/`（请求**无权控闸**，服务端全局持有）。
  3. **双形态**：形态一**独立 serve**（`context_kernel/serve/server.py`，纯标准库，`python -m context_kernel.serve.server`）——ck 的「独立消费面」，可独立部署；形态二**组件集成**（`from context_kernel import ContextKernel` + 自装配 LlmProvider/DataPlane，只改 import 不碰内核）。`core/` + `ports/` 零外部依赖，差异全收在 `adapters/`。
- **路由到项目真源（自证坐标）**：
  - `src/ck-py/context_kernel/core/context_kernel.py` L22（`ContextKernel`：内核本体）
  - `src/ck-py/context_kernel/core/`（assembler / gate / gate_config / models——拼装与闸分离，零外部依赖）
  - `src/ck-py/context_kernel/serve/server.py` L115（`CKHandler`：独立消费面，纯标准库）；L226（`build_app`）；L245（`main`）
  - `src/ck-py/context_kernel/serve/session_store.py`（两层 Session：永久区 persona/doc + 临时滑动窗口 deque maxlen=20）
  - `src/ck-py/context_kernel/ports/`（`LlmProvider` / `DataPlane` / `ContextSource` 端口——差异在 adapters 注入）
  - `src/ck-py/docs/user-manual_zh.md`（推理闸机制手册：红线⑥ 闸不回写会话；双形态）

### "项目如何做后台管理？——静态面板 + 事件总线全链路可观测 + 离线分析"
- **关键字**：`后台管理` `public` `admin.py` `sessions/tasks/jobs` `自动刷新` `事件总线` `/admin/listeners` `events.jsonl` `/admin/analysis` `用户管理`
- **项目自评**：
  1. **它是什么**：管理面 = `src/sl-py/public/`（**静态 HTML 面板**：sessions / tasks / jobs）+ `src/sl-py/app/routers/admin.py`（路由）——会话监控（**5s 自动刷新**）、任务链监控、Job 管理、用户管理（CRUD + 创建用户自动联动 strata-match 注册 `sm-{uuid}`），另有 `/admin` dashboard 首页卡片导航。
  2. **事件总线（全链路可观测）**：`/admin/listeners` 创建/查询/删除监听 Job——**所有 dispatch 决策、strata-match 调用、任务链步骤都推送事件**；`data/events.jsonl` 持久化事件日志，不依赖 grep 日志。
  3. **离线分析**：`/admin/analysis` 读 `events.jsonl`，经 `Analysis` 服务生成事件分析报告——事后审计/复盘不用翻日志。
- **路由到项目真源（自证坐标）**：
  - `src/sl-py/public/`（sessions.html / tasks.html / jobs.html 静态面板；sessions 5s 自动刷新）
  - `src/sl-py/app/routers/admin.py` L61（`/admin` dashboard 首页）；L91–108（sessions / tasks / jobs 面板）；L146–208（users CRUD + 面板，联动 strata-match）；L28–51（`/admin/listeners` 事件总线）；L261–269（`/admin/analysis` 离线分析，读 `events.jsonl`）
  - `src/sl-py/data/events.jsonl`（事件日志持久化，分析数据源）

---

## License / 许可证

**Apache 2.0** · [LICENSE](LICENSE) · [GitHub](https://github.com/weihai-limh/synth-loop)
