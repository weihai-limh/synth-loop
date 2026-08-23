# context-kernel 改造与 synth-loop 集成草案（v0.1.2_b 第二步）

> 状态：**讨论草案，持续演进。** v3 = 在 v2 基础上修正「分形路由归属」：分形路由（取哪些 sm prompt、选哪个规格模型等决策）归属 sl 上游层，经 `build_messages` 生成初始上下文后进 ck；ck 退回纯「上下文管理 + 闸引擎」内核。新增「开放闸 = HTTP 钩子」语义：闸响应经 HTTP 端口暴露，外挂改进服务为 sl 之外的独立后续服务，本草案只以闸形式留钩子。所有结论均经代码实证。
> **v3.2 更正（代码实证）**：① **G4 开放闸 HTTP 接口 ck 已实做**——`core/gate.py`（`gate_get/gate_set`）+ `serve/server.py`（park/peek/amend HTTP）即参照实现，本草案 G4 从「待建」降为「sl 侧对接消费」；② **`context_compressor` 落点已决**——对 ck 装配产出的 `AssembledContext.region_index` 做 region 级 drop/compress（同 ck 外挂示例服务的 region+次序视图变换逻辑），置于 sl 推送前、模型窗口感知、不进 ck 内核；③ ck 的 region 分区（`session_id/permanent/loaded_docs/client_system/temp/current`）即天然优先级层级，无需 build_messages 另打标签。
> 目的：固化「ck 作为 sl 主路径上下文管理核心 + 闸引擎（分形路由在 sl 上游），统一推理收束」的蓝图，作为对齐 sl 预期架构的基线。
> sk 已澄清为笔误——集成对象仅 **ck（context-kernel）+ pk（phase-kernel）** 两内核。
> 来源材料：`concept_V0_1_2_b_zh.md`、`other/phase-kernel/docs/design_zh.md`、`other/context-kernel/docs/design_zh.md`。
> **v3.3 更正（用户对齐·模型分形家族化）**：① `tier` 概念从家族彻底出局——pk 改造点、pk 外挂字段、ck G1 的 tier 处理全部清零；② **pk 的模型路由属 pk 外挂服务（与 ck 外挂同构的 peer 外部服务），不在 pk 内核、不归 sl 所有**；③ **pk 外挂的字段命名与模型选择语义须双向对齐 sl 的分形家族（sl 分形=家族正统叙事），愈合研发期从 sl 孵出后的分叉**；④ 因无 `tier`，ck G1 不再背负 tier 转发僵尸路径（内核更轻），sl→ck→pk 边界少一处静默错配脆弱点；⑤ 合并分叉须**尽早**（前置到 pk 改造早期）。
> **v3.4 更正（§11.4 记忆/数据面预埋钩子）**：新增 §11.4（记忆片段以 `loaded_docs` 形式注入永久区，复用 sl 既有 `<user-memory>` 标签族 + 永久区 `permanent_system_prompt`+`loaded_docs` 装配，不新造 store、不新造 `<sl-memory>` 标签）；并在 §11.1–11.3 各片末尾预埋「供 §11.4 复用的钩子」——实施 11.1~11.3 时**不得破坏**：① `build_messages` 须保留记忆 id 引用解析的单一落点（占位 no-op 即可）；② ck/sl 的 region 分区（`permanent`+`loaded_docs`）须保持为规范契约、记忆片段落 `loaded_docs` 区；③ 数据面适配层须视记忆片段为合法数据面载荷；④ `<user-memory>` 标签须由 `chat.py._extract_user_memory` 单一持有、可扩展携带 `id`；⑤ `load_document`/`unload_document` + `context_manager` 须保留为永久区 I/O 原语、可加 id 句柄变体。
> **v3.5 更正（附录 B·认知对齐）**：明确指出「编排网关」是错误认知——sl 以 OpenAI 兼容 chat 接口对外暴露仅是其**集成面**（让 sl 更易被集成的形态），非 sl 本质；sl 本质 = 拥有家族分形叙事权威的**分形编排控制面**，内含原生 tool-call 循环（prompt_chat 分支 `for loop in range(max_loop)`），编排 ck/pk 通用内核；task_chain/phase 为分形路由 a-f 分支。
> **v3.6 补充（价值外溢）**：sl 把分形路由 + 上下文装配（ck）+ 推理缝（build_messages）+ 模型选择语义等重活**收在自己身上**，故对接 sl 的 agent 可变得更薄、甚至薄成一个仅封装 chat 调用 + 工具注册的 **SDK**；**记忆仍由 agent 维护**，区别仅在于 sl 后续暴露的 API 可按固定格式机械化注入/卸载记忆、再在 chat 中以引用使用（§11.4）。B.2 的「chat 接口仅易集成」进一步外溢为价值——标准 chat 接口正是「对接方变薄」的使能器。与「编排网关」错误认知对照：sl 非透传复杂度，而是**吞下复杂度**让下游变薄（见附录 B.5）。
> **v3.7 更正（叙事立场·B.6）**：以「局部领先/整体不领先」做工程对比的口径**不成立**——「自主 loop」是模型厂商叙事（上游供给侧，卖模型能力），「路由+上下文内核」是 LLM 实际执行度叙事（下游使用侧，关心 execution degree）；二者非同一维度强弱比，sl 不在模型厂商的叙事场上，其场是「LLM 的实际执行度」。分形成本意识/上下文内核化/薄成 SDK 收口为一条轴：一切为 LLM 实际执行度。同步修正 B.5 推论句。

---

## 1. 目标与定位

- **ck 作为 sl 主路径上下文管理核心 + 闸引擎**：接管 sl 散落 `context_*` 模块群（装配），并内置「开放闸」双功能接口（开闭态 + 结构化闸响应）。**分形路由不在 ck 内**——分形决策（取哪些 sm prompt、选哪个规格模型、async/任务链意图）由 sl 上游持有，经 `build_messages` 生成初始上下文后进 ck。
- **pk `InferenceSeam` 的 sl 集成点 = `build_messages`（非 ck）**：所有请求统一从 `chat.py handler` 进入，相位只是 sl 分形路由识别出的**一种特殊分形路由**；相位执行经 `InferenceSeam` 桥落到 sl 的 `build_messages`（与 tool/task/phase 等其他分形产出同处收束），再经 `sl_llm_provider`（推理收束唯一落点）出。ck 在链中是 `build_messages` 的内部依赖（取会话快照），**不是 `infer` 的直接落点**。
- **集成形态 = 组件文件夹（vendored + 热替换）**：ck/pk 以可替换文件夹集成进 sl，后续内核更新只需替换文件夹；sl 与内核之间以**稳定适配层**隔离（只依赖内核公开接口，不依赖内部实现）。
- **sl 新增「统一的闸管理」**：对外暴露 ck 的闸、pk 的闸、未来其他闸；ck **已实做**「开放闸」HTTP 接口（`core/gate.py` 的 `gate_get/gate_set` + `serve/server.py` 的 park/peek/amend），sl 仅须 `gate_manager` **对接消费**并聚合对外。

---

## 2. 已锁定决策（v2）

1. **推理收束统一（seam 集成点 = build_messages）**：ck 是主路径上下文核；pk 的 `InferenceSeam` 在 sl 中**以 `build_messages` 为集成点（非 ck）**——ck 在链中是 `build_messages` 的内部依赖（取会话快照）。所有路径最终收敛到同一 `sl_llm_provider`。
2. **ContextSource 预组装**：sl 策略注入（XML `<context>`/asset/injection_pipeline/system_prompt）在 sl 侧 `ContextSource` 预组装进 persona 层，ck 只按序摆放。
3. **分叉1（chat.py 留编排）**：chat.py 保留请求级编排（pre-check / user-memory / packets / 相位路由 / 复杂度分类），只把上下文装配下沉 ck。
4. **分叉2（sl_llm_provider 放 services/）**：`sl_llm_provider` 置于 `services/`，并适配「改造后的 ck」。
5. **分叉3（分形路由在 sl 上游，ck 为上下文核）**：分形路由（决策：取哪些 sm prompt、选哪个规格模型、async/任务链意图）由 sl 上游持有，经 `build_messages` 生成**初始上下文**后进 ck；ck 与其他分形产出的张力由 **sl 新增 `build_messages` 服务**收束，ck 向该服务**单向提供**基于会话**快照**的装配消息（**不回灌**，ck 只读快照、只改请求侧数据）。ck 不退化为分形路由决策方，只做上下文装配 + 闸。
6. **统一闸管理**：sl 新增 `gate_manager`，对外暴露 ck/pk/未来闸。
7. **ck 已实做开放闸接口（代码实证）**：`ContextKernel` 已实现 `gate_get/gate_set/set_gate_mode`，`serve/server.py` 经 HTTP 暴露 park/peek/amend（即开闸态 `get/set` 钩子面）。sl 侧 `gate_manager` 对接消费即可（支撑统一闸管理）。
8. **组件文件夹集成（sk=笔误）**：ck/pk 以 vendored 文件夹集成，sl 仅依赖其公开 API；热更新仅替换文件夹。集成对象仅 ck+pk。

---

## 3. 目标架构

```
                  ┌──────────────────────────────────┐
   外部请求 ─────► │  sl 统一闸管理 gate_manager        │  ← 对外暴露 ck/pk/未来闸
                  │  (调度 ck 开放闸接口 + pk 闸 + …)   │
                  │  闸响应/钩子经 HTTP 端口暴露→外挂服务│
                  └────────────────┬─────────────────┘
                                   │ 闸控 + 路由
                                   ▼
  sl 分形路由(上游, 自持)                        ┌──────────────────────────────┐
   (取sm prompt/选模型规格/async/task/相位 意图；  │  ck（上下文管理 + 闸引擎）      │
    相位为特殊分形路由)                           │                              │
        │                                        │  · 上下文装配 + 六层            │
        ▼ 经 sl build_messages 生成初始上下文       │  · 开放闸接口(get/set 钩子)    │
  主路径请求/分形产出 ─────────────────────────► │  · 不持有分形路由决策           │
                                                └───────────────┬──────────────┘
                                                   │ 单向：ck 提供装配消息(快照)
                                                   ▼
                                   ┌──────────────────────────────────┐
                                   │  sl build_messages 服务            │
                                   │  (收束其他分形产出:                │
                                   │   tool / task / phase 结果)        │
                                   └───────────────┬──────────────────┘
                                                   │ 推理收束
                                                   ▼
                                   ┌──────────────────────────────────┐
                                   │  sl_llm_provider (services/)       │  ← 唯一推理收束点
                                   │  (DownstreamLLM.chat_with_        │
                                   │   degradation + streaming_handler) │
                                   └──────────────────────────────────┘

  pk 相位推理（特殊分形路由分支，入口仍是 chat.py handler）
   chat.py handler → sl 分形路由(识别相位意图) → pk.phase_executor
     ──via sl.InferenceSeam.infer(context_patch)──► build_messages
        (喂 context_patch 为「其他分形产出」; 内部调 ck 取会话快照装配;
         模型选择语义（对齐 sl 分形家族）在此翻译) ──► sl_llm_provider
     （*模型路由属 pk 外挂服务（peer 外部服务，同 ck 外挂）；pk 内核不内嵌模型路由。
       pk 外挂字段命名与模型选择语义对齐 sl 分形家族（sl 分形=正统叙事），`tier` 已出局；
       seam 集成点在 build_messages，不在 ck。详见 §11.2）

  组件文件夹（vendored 纯副本，可热替换，sk=笔误故仅 ck+pk）:
    src/app/kernels/context_kernel/   ← ck（G1–G2；G4 开放闸已实做于 ck，sl 仅对接；G5 修正不进 ck）
    src/app/kernels/phase_kernel/     ← pk
  稳定适配边界（只依赖公开 API，热替换不破 sl）:
    sl_session_source / sl_inference_provider / sl_data_plane

  闸循环：入口请求经 `gate_manager` 选中的预制组合函数 → 命中闸发出**结构化闸响应**
  → `build_messages` 按 `context_delta` 重装配（再次请求）→ 循环至 `final` 响应。
  ck standalone 时无 `gate_manager`，由 ck 自带通用闸引擎跑同构循环。
```

---

## 4. 代码实证的关键契约（承重墙，已读源码确认）

| 项 | 代码真相 | 出处 |
|---|---|---|
| `ContextKernel` 构造签名 | `(context_source, data_plane, llm_provider, primary_model, fallback_model, gate_mode, context_mode)` | `core/context_kernel.py:22` |
| `SessionView` 字段 | 仅 `{permanent_system_prompt, loaded_docs:list[dict], temp_history:list}` | `core/models.py` |
| `run_openai(body)` 契约 | 读 `metadata.{session_id, client_system_messages, override_system, ext}` + `messages` 末条 user | `core/context_kernel.py:63` |
| 六层拼装顺序 | 逐层对齐 sl `build_messages`（assembler 自述） | `core/assembler.py` |
| `build_prompt` 已导出 | sl 工具循环/收束路径可直用 | `__init__.py:16,35` |
| `infer()` = `NotImplementedError` | 由 sl 侧桥接 pk 缝 | `core/context_kernel.py:58` |
| `DataPlane` 在 `run_openai` 路径未被调用 | 主路径 packets 经 `metadata.client_system_messages` 传入 | 全路径扫描 |
| **适配约束** | sl 适配器只 import `context_kernel` 公开 API，不触内部模块 → 支撑组件文件夹热替换 | 本草案 §7 |
| **开放闸接口已实做** | `ContextKernel.gate_get/gate_set/set_gate_mode` 已存在；`serve/server.py` 经 HTTP 暴露 park（`POST /v1/chat/completions` auto）/peek（`GET /chatgate/{id}`）/amend（`POST /chatgate/{id}`）——即「开闸态 get/set 钩子面」参照实现 | `core/context_kernel.py:169-205` + `serve/server.py` + `core/gate.py` |
| **装配产物带 region 分区** | `AssembledContext.region_index` 将消息按区划分区（`session_id/permanent/loaded_docs/client_system/temp/current`），`extract_custom_context`/`reassemble_from_custom` 按 region+次序、只 content 无 role 操作——context_compressor 直接消费此视图 | `core/gate.py:61-91` + `core/assembler.py` |

---

## 5. ck 缺口与改造（G1–G5）

| 缺口 | 代码位置 | 修复（落在 vendored ck 文件夹） |
|---|---|---|
| **G1** 忽略 `body["model"]`（`fallback_model` 零引用）；`ext.tier` **已不存在于家族**（v3.3：tier 出局，ck 不再背负其转发僵尸路径） | `context_kernel.py:157-158` 与 `194-195`（reassemble 重试分支**共两处**） | `run_openai` 提取 `body["model"]`（+`ext["service_name"]`），透传 `chat(messages, model, stream, service_name=)`；**不再处理 `tier`**——内核更轻、边界少一脆弱点 |
| **G2** 流式硬编码 `False`，无流式分支 | 同上两处 `stream=False` | `run_openai` 读 `body["stream"]`，为真时返回流而非 `InferenceResult` |
| **G3（v4 更正：必须修·原"不改"系概念错误）** 返回层只剥 `content`，丢 `tool_calls`——分形全部走 ck，此丢弃**阻断 sl 经 ck 调工具**（与「ck 是 sl 主路径上下文管理核心」自相矛盾） | `core/context_kernel.py:157-166`（closed 直推）+ `:194-197`（gate_set 修正推）两处只取 `response[...]["message"]["content"]`；`response[...]["message"]["tool_calls"]` 被丢弃 | **G3 必须修**：`InferenceResult` 增 `tool_calls` 字段，两返回层从 `message` 原样透传 `tool_calls`；sl 在 ck 完整响应上做工具调度循环（sl 职责，不归 ck）；ck 独立外挂 `serve/` envelope + `CK_SCHEMA` 同步透传（见 `concept_ck_zh.md` §2.5/§6.6/§九 E5 + `development-plan_ck_zh.md` Phase 2.6/3.5） |
| **G4（已实做·v3.2 更正）** ck 开放闸 HTTP 接口 **ck 已实现**（`gate_get/gate_set/set_gate_mode` + `serve/server.py` park/peek/amend） | 原误判为「未暴露」——实际 `core/gate.py`+`serve/server.py` 已落地 park/peek/amend 协议（开闸态 `get/set` 钩子面），正是 §5.6 的参照实现 | **不再视为 ck 待建项**。sl 侧 `gate_manager` 仅需**对接消费**该 HTTP 协议并聚合并暴露。注：§5.5 的「结构化 `GateResponse`{decision,context_delta,rerequest_directive} + 预制组合函数注册表 + 跨内核循环」属 **sl `gate_manager`** 的高层设计（消费 ck 闸原语），非 ck 职责 |
| **G5（新·修正 v3）** ck 不持有分形路由 | sl 的 `_handle_fractal_dispatch`+`_classify_by_fractal`+`FRACTAL_ROUTE_MAP` 现堆在 `chat.py`，属「分形路由决策」，应在 sl 上游（不进 ck，避免污染内核稳定性） | **不在 ck 内新增分形路由**。改为：ck 在**开闸态暴露 `get/set` 可编程钩子面（HTTP）**——供 sl 之外的外挂改进服务读取分形决策+上下文、回写改进、并记循环提升 sm 策略（详见 §5.6）；分形路由决策仍由 sl 经 `build_messages` 产出初始上下文后进 ck |

---

## 5.5 闸模型（Gate Model，v2 关键）

基于用户决策锁定：

- **闸的两层作用**：① **开闭闸**（开/关状态，对应 `gate_mode`）；② **闸响应**（闸被触发时发出的**结构化信令**，非简单放行/拦截）。
- **闸响应形态（结构化信令）**：
  ```
  GateResponse {
    decision: pass | redirect | augment | block,
    context_delta: {...},          # 重请求时上下文增量
    rerequest_directive: {...},    # 如何再次请求
  }
  ```
  经此，`build_messages` 可程序化消费「再次请求」做重装配。
- **组合语义 = 预制闸的组合逻辑函数**：sl 不跑通用声明式解析器，而是提供**一组预制的组合逻辑函数**（命名、可复用），每个函数封装「哪些闸 + 如何组合」，对应一种响应模式。「不同闸的组合造成不同响应」即由不同预制函数实现。`gate_manager` 是这些函数的**注册表/集合**，按请求类型/策略选函数执行。
- **循环归属**：ck 自带**单内核通用闸引擎**（ck standalone 也能跑 `入口→闸响应→再次请求→最终响应`）；**sl `gate_manager` 负责组合 ck/pk/未来多内核闸、并拥有跨内核循环**。ck 仍独立，sl 做编排。（开放闸接口以 **HTTP 端口**对外暴露，详见 §5.6）

## 5.6 开放闸 = HTTP 钩子 + 外挂改进服务（v3 新增）

基于用户决策锁定：

- **闸响应经 HTTP 端口暴露（ck 已实做，v3.2 更正）**：ck 的开放闸接口 **并非待建**——`core/gate.py`（`gate_get/gate_set`）+ `serve/server.py` 已实现 park/peek/amend 的 HTTP 协议（`POST /v1/chat/completions` auto→park；`GET/POST /chatgate/{id}`；`GET/POST /context-conf/`）。这正是「开闸态 `get/set` 钩子面」的参照实现。`gate_manager` 负责把 ck/pk/未来闸的响应聚合并对 sl 外暴露（外挂改进服务消费）。
- **外挂改进服务 = sl 之外的独立后续服务（out-of-scope）**：本草案**只以闸的形式留钩子**，不实现该服务。其未来职责（见下）归属外部服务，sl 不拥有：
  - 消费 HTTP 闸响应 / `get` 当前分形决策 + ck 装配上下文；
  - `set` 回写对分形路由 / 模型选择的改进；
  - 记录一轮「入口→闸响应→重请求→最终响应」**循环**；
  - 累积循环反馈给 strata-match，**提升 sm 策略水平**（下次选 prompt / 模型更准）。
- **开闸态 = 可编程改进面**：`gate_mode=open` 时闸暴露 `get/set` 钩子面；`gate_mode=closed` 时仅内部 pass/block，闸响应不外泄（纯功能态）。这与 ck「通用态、可脱离 sl 独立运行、接不接无影响」不冲突——钩子是**可选暴露**，不接不影响内核。
- **sl 仅留钩子，不拥有学习环**：循环记录与 sm 反馈归外挂服务，sl 保持薄。sl 侧需提供的只是 **HTTP 闸端点契约**（`services/gate_manager.py` 暴露 HTTP 面 + `get/set`，见 §8）。

## 6. sl 新增 / 调整组件

1. **`gate_manager`（统一闸管理，新增）**：sl 对外的闸控面。持有 ck 闸 + pk 闸 + 未来闸的开放接口；内部是**预制闸组合逻辑函数的注册表**——每个函数封装一种闸组合（对应一种响应模式），按请求类型/策略选函数执行，拥有**跨内核循环**（`入口→闸响应→再次请求→最终响应`）。闸的语义仍由各内核自持（ck 通用闸原语），`gate_manager` 只做组合编排与对外暴露。**并对外暴露 HTTP 闸端点**（结构化 `GateResponse` 流 + `get/set` 钩子面），供外部改进服务（§5.6）消费——sl 只留钩子，不实现学习环。
2. **`build_messages` 服务（新增，单向收束、不回灌）**：ck 基于会话**快照**装配出消息（ck 只读快照、只改请求侧数据），本服务再把「其他分形产出」（tool 执行结果、task_chain 结果、phase 产物、闸 `context_delta` 等）汇入，产出**重请求消息**交给 `sl_llm_provider`。**不回灌 ck**——会话状态归 sl（`SessionManager`/`context_manager`），ck 的快照读取是瞬时的。`sl` 分形路由的产出（选中的 sm prompt / 模型规格 / async 意图 / 任务链）作为 ck 装配输入（经 `sl_session_source` 预组装进 persona），而非由本服务回写 ck。
3. **`sl_llm_provider`（services/，分叉2）**：薄包 `DownstreamLLM.chat_with_degradation`（接上潜伏降级链）+ `streaming_handler.stream_openai`（流式分支）。`chat(messages, model, stream, tools, service_name, api_key)`（**不含 `tier`**）。推理收束唯一落点。
4. **稳定适配层（adapters）**：`sl_session_source`（ContextSource 读 Session + persona 预组装）、`sl_inference_provider`（即 `sl_llm_provider`，实现 ck `LlmProvider`）、`sl_data_plane`（仅相位 artifacts 走 pk `ArtifactStore`）。**只依赖 ck/pk 公开 API**，是热替换的稳定边界。
5. **`pk_inference_seam`（pk 步，集成点 = `build_messages`）**：`infer(context_patch)→build_messages(喂 context_patch 为其他分形产出; 统一分形模型语义翻译在此; 内部调 ck 取会话快照装配)→sl_llm_provider→InferenceResult`。**ck 不是 `infer` 的直接落点**——它是 `build_messages` 的内部依赖（提供会话快照装配），相位 `context_patch` 作为「其他分形产出」汇入收束，而非进 ck 的会话装配。（pk 模型路由属 pk 外挂、字段/语义对齐 sl 分形家族，见 §11.2）

### sl_llm_provider 设计要点
- `DownstreamLLM` 本身是合法 `LlmProvider`，`SLInferenceProvider` 薄包——接下降级链 + 分流流式。
- 模型选择仍在 sl（`ModelSelector`，进 ck 前），结果塞 `body["model"]`+`ext`，经 G1 转发。
- 双降级归位：LLM 传输降级 = `chat_with_degradation`（接进 sl_llm_provider）；strata 策略降级 = `SmartPromptDegradation`（留 `first_turn_prompt_selection`）。
- 流式分支：`stream=True` 走 `streaming_handler.stream_openai`，不走 `chat`。

---

## 7. 组件文件夹集成模型（v2 新增，对应决策 8）

- ck/pk 以 **vendored 文件夹（纯副本）** 集成：`src/app/kernels/context_kernel/`、`src/app/kernels/phase_kernel/`；机制 = **纯副本**（非 git-submodule），内核更新时整体替换对应文件夹即可。
- sl **只 `import` 内核公开接口**（`from context_kernel import ContextKernel, ...`），绝不 import 其内部子模块 → 内核内部变更不波及 sl。
- 稳定适配层（§6.4）是隔离带：内核更新时，仅适配层可能需要微调；热更新 = 整体替换 `kernels/` 下对应文件夹。
- ck 改造（**G1–G2**；**G4 开放闸已实做于 ck**，sl 仅对接消费）**落在 vendored 纯副本**；待 ck 上游发布新版，sl 直接整体替换 `kernels/context_kernel/` 文件夹（适配层对齐公开 API 即可）。

---

## 8. 文件级改动清单

### ck vendored 文件夹（G1–G2；G4 已实做于 ck，sl 仅对接）
- `kernels/context_kernel/core/context_kernel.py`：**G1（两处 `model` 转发，`tier` 已出局）+ G2（两处流式分支）**——两处 `llm_provider.chat(..., self.primary_model, stream=False)`（`context_kernel.py:157-158` 与 `194-195`）。
- **G4（v3.2 更正：ck 已实做，非待建）**：`gate_get/gate_set/set_gate_mode` + `serve/server.py` park/peek/amend 已落地；sl 侧 `gate_manager` 对接消费，无需改 ck。G5 已修正——ck **不新增分形路由**，开闸态 `get/set` 钩子面已由 serve 暴露。

### sl 仓库（新增，不删旧件直到验证）
- `src/app/kernels/context_kernel/`、`src/app/kernels/phase_kernel/`（vendored）。
- `src/app/integrations/context_kernel/{runtime.py, sl_session_source.py, sl_inference_provider.py, sl_data_plane.py, pk_inference_seam.py}`（稳定适配层）。
- `src/app/services/gate_manager.py`（统一闸管理）。
- `src/app/services/build_messages.py`（分形产出收束）。
- `src/app/services/sl_inference_provider.py` 或并入 `downstream_llm`（分叉2 落 services/）。
- 改 `src/app/routers/chat.py`：handler 调 ck（先 `_handle_chat_level` 试点）；**分形路由决策保留在 sl 上游**（G5 修正：不进 ck，仍由 `_classify_by_fractal`/`FRACTAL_ROUTE_MAP` 等在 sl 侧，产出初始上下文经 `build_messages` 进 ck）。

### 退役（验证后）
`context_router` / `context_injector` / `system_prompt_builder` / `asset_consumer` / `injection_pipeline` —— 逻辑迁入 `sl_session_source` 预组装 / `build_messages` 收束。

### 保留
`context_manager`（写方）、`context_compressor`（**推送前 region 级 drop/compress 变换，同 ck 外挂示例服务的 region+次序视图逻辑，见 #6 已决**）、`session_manager`、`downstream_llm`、`model_selector`、`streaming_handler`、`degradation_manager`（strata 侧）、`tool_dispatcher`、`dynamic_tool_executor`。

---

## 9. 增量切片（v2）

- **Slice 0**：组件文件夹落地（ck/pk vendored）+ 稳定适配层骨架 + `sl_llm_provider`（services/）。低风险，建立热替换边界。
- **Slice 1**：ck **G1/G2**（model 转发 + 流式；`tier` 已出局不处理） + 用 `ck.run_openai` 包住 `_handle_chat_level`（单路径 PoC），对齐行为。（G4 开放闸 ck 已实做，本片仅验证 sl 对接路径）
- **Slice 2**：sl `build_messages` 单向收束其他分形产出（ck 提供装配消息，不回灌），分形路由保留在 sl 上游（G5 修正：不进 ck）；退役 5 个 context 模块。
- **Slice 3**：sl `gate_manager` 对接 **ck 已实做的开放闸**（park/peek/amend）+ 统一闸管理；pk 集成 + `InferenceSeam.infer→build_messages` 桥（ck 由 build_messages 内部调用取会话快照），推理收束统一。

每片 ≤3 文件、不跨主线、不动对外 API，可随时回退。

---

## 10. 风险与待裁决

### 风险
- **低**：sl 侧拼装已有零件；ck 核心（assembler/gate/models）已验全绿；六层顺序对齐；`SessionView` 字段吻合。
- **中**：**G1/G2 需改 ck**（已定位，两处 `model` 转发 + 两处流式分支，小改；`tier` 已出局故不处理）；**G4 开放闸 ck 已实做**（v3.2 更正），sl 仅需对接消费；组件文件夹隔离需严守「只依赖公开 API」。G5 已修正为「不进 ck、仅暴露钩子」，ck 改造面收敛为仅 G1/G2。
- **Open**：`context_compressor` 落点（ContextSource 预组装 vs gate 前 transform）。

### 待裁决（需用户拍板）
1. **统一闸管理边界（已决）**：`gate_manager` = 跨内核协调者（持有预制闸组合逻辑函数注册表，拥有跨内核循环）；闸语义仍由各内核自持（ck 通用闸原语 + 结构化闸响应）。G4 形态已定：ck 暴露双功能通用闸接口（开闭态 + 结构化闸响应）+ 单内核通用闸引擎。
2. **`build_messages`↔ck 交换契约（已决）**：ck 基于会话**快照**装配，只读不写、只改请求侧数据，**不回灌**。`ck` 单向向 `build_messages` 提供装配消息；`build_messages` 汇入其他分形产出 + 闸 `context_delta` → 重请求消息 → `sl_llm_provider`。会话状态归 sl。
3. **G5 分形路由归属（已决·v3）**：分形路由（取 sm prompt / 选模型规格等决策）**归属 sl 上游**，不进 ck；ck 在开闸态暴露 `get/set` HTTP 钩子供外挂改进服务消费。已写入 §5.6 / G5 修正。
4. **组件文件夹路径与 vendoring 机制（已决）**：路径 `src/app/kernels/`；机制 = **纯副本**（非 git-submodule），热更新整体替换对应文件夹。
5. **`anthropic_chat.py`（已决·冻结）**：本批**先冻结**，待 OpenAI 主路径（chat.py）改造完成后再统一改造。
6. **`context_compressor` 落点（已决·v3.2）**：对 ck 装配产出的 `AssembledContext.region_index` 做 **region 级 drop/compress**——`loaded_docs`/`temp` 为低优可裁区，`permanent`/`session_id`/`current` 保底；**同 ck 外挂示例服务（serve/server.py + gate.py）的 region+次序内容视图变换逻辑**（仅目的不同：压缩 vs 修正）。置于 **sl 推送前**（`build_messages` 产出后、`sl_llm_provider` 前），**模型窗口感知**（阈值来自 ModelSelector 选定的目标模型），**不进 ck 内核**（保通用）。无需 build_messages 另打优先级标签——ck 的 region 分区即天然层级。

---

## 11. 改造次序（ck → pk → sl）

依赖顺序：ck 是内核基座，pk 在其上定义相位语义，sl 最后把三者接线。前置改造必须先于依赖方落地。

### 11.1 ck（先）
- 落地 **G1–G2–G3**（model 转发 + 流式分支 + **tool_calls 透传修复**；`tier` 已出局不处理）。**G3 为 v4 更正——原"不改 ck、sl 绕开 ck 调工具"系概念错误**：分形全部走 ck，ck 返回层丢 `tool_calls` 阻断 sl 经 ck 调工具，故 **G3 必须修**——ck 返回层（`_assemble_and_gate` 两处）原样透传 `tool_calls`，sl 在 ck 完整响应上做工具调度循环；ck 独立外挂 `serve/` envelope + `CK_SCHEMA` 同步透传。详见 `concept_ck_zh.md` §2.5/§6.6/§九 E5 与 `development-plan_ck_zh.md` Phase 2.6/3.5。
- **G4 开放闸已实做于 ck**（gate.py + serve/server.py），保持零 sl 依赖、可 standalone，sl 后续对接消费即可。
- 闸接口（开闭态 + park/peek/amend `get/set` 钩子面）**ck 已就绪**（v3.2 更正）；sl 的「结构化 `GateResponse` + 预制组合函数 + 跨内核循环」属 `gate_manager`（sl 侧），pk / sl 对接消费即可。

> ⚠ **预埋钩子（供 §11.4 记忆/数据面复用，本片实施不得破坏）**：ck 的 `region_index` 分区（`session_id/permanent/loaded_docs/client_system/temp/current`）须保持为**规范契约**，不得合并/重命名区域。§11.4 的记忆片段将解析进 `loaded_docs` 区；若本片改动 region 语义，须同步通知 §11.4。

### 11.2 pk（次，改造须前置·v3.3）

- **pk 改造点（关键·v3.3 家族化）**：模型路由**不属于 pk 内核**，而属于 **pk 的外挂服务**——与 ck 的外挂同构的 peer 外部服务（经闸/hook 与内核交互），**不归 sl 所有**。
  - **`tier` 彻底出局**：从 pk 改造点、pk 外挂的字段命名中完全剔除，不留兼容别名。
  - **pk 外挂双向对齐 sl 分形家族（字段命名 + 语义）**：表达模型意图的字段沿用 sl 分形家族同一套词汇与命名（如 sl `llm_routing` / 场景标签 / 复杂度字段），不另起一套；语义与 sl 的分形模型选择同源。
  - **理由（愈合分叉）**：pk 的外挂本由 sl 孵化出去，研发期出现分叉才长出独立 `tier`/路由；sl 的分形是家族**正统叙事**，是所有人对齐的准绳。故对齐方向是 pk 外挂 → sl 分形，而非各立一套。「内核语义同意」——ck/pk 通用内核均认同一份语义契约，能力外置为外挂服务。
  - **合并分叉须尽早**：去 `tier` + 字段/语义对齐 sl 分形，应前置到 pk 改造早期，避免分叉继续生长。
  - 此点已同步修正 §3 架构图与 §6 的相关描述（「统一分形模型语义」→「pk 外挂对齐 sl 分形家族」）。
- pk **仅依赖 `InferenceSeam` 抽象**：相位执行调用 `infer(context_patch)`，由 sl 实现为——喂 `context_patch` 进 `build_messages`（作为「其他分形产出」汇入）→ 内部调 ck 取会话快照 → `sl_llm_provider`。**ck 不直接被 pk 依赖**，藏在 sl 的 `build_messages` 内部——进一步强化组件隔离（pk 只认缝，不认 ck）。

> ⚠ **预埋钩子（供 §11.4 复用，本片实施不得破坏）**：pk 内核与外挂**不得引入竞争性记忆标签**。记忆标签词汇归 sl 家族（`<user-memory>` 及其 `id` 扩展），pk 侧只认语义、不发明标签；若 pk 外挂涉及记忆/上下文标签，须复用 sl 标签族，不得 fork。

### 11.3 sl（最后）
- 组件文件夹 vendored（ck / pk 就绪后整体替换）。
- 稳定适配层：`sl_session_source` / `sl_inference_provider` / `sl_data_plane`。
- `build_messages`（收束分形产出）、`gate_manager`（统一闸 + HTTP 暴露）、`sl_llm_provider`（services/）。
- 改 `chat.py`：保留请求编排（含分形路由决策，相位为特殊分支），下沉上下文装配 + 闸给 ck。

> ⚠ **预埋钩子（供 §11.4 记忆/数据面复用，本片实施不得破坏）**：
> - **`build_messages` 须保留「记忆 id 引用解析」单一落点**：本片落地时在该步骤放**占位 no-op**（钩子就位但暂不实装），§11.4 填入 `<user-memory id="x"/>` → 查永久区 → 命中展开为 `loaded_docs` 形式、未命中原样保留标签文本的逻辑；不得把消息装配写死以致无解析缝。
> - **永久区结构契约**：`context_router` 的永久区装配（`permanent_system_prompt` + 已加载文档 `loaded_docs`，`context_router.py:45-59`）须保持；记忆片段落 `loaded_docs` 区，不并入 `permanent_system_prompt`。
> - **`<user-memory>` 标签单一持有**：`chat.py._extract_user_memory`（`chat.py:593/614`）须仍是该标签唯一所有者，重构时不得移除/改写其职责，且须可扩展携带 `id`（提取 vs 引用两种模式）。
> - **永久区 I/O 原语保留**：`load_document`/`unload_document` + `context_manager` 的 load/unload/list/refresh 须保留为永久区读写原语；§11.4 的「注入返回 id / 卸载」在其上叠加 id 句柄变体，本片不得替换掉这些原语。
> - **数据面载荷**：`sl_data_plane` 适配层须视记忆片段为合法数据面载荷（解析为 `loaded_docs`），不得特殊剔除。
> **v3.5 更正（附录 B·sl 新架构认知）**：新增「附录 B：对 sl 新架构的认知（供对齐）」——明确指出 **「编排网关」是错误认知**：sl 以 OpenAI 兼容 chat 接口对外暴露，仅是**让 sl 更易被集成的形态（集成面）**，并非 sl 的本质/身份；sl 本质 = 拥有家族分形叙事权威的分形编排控制面，内含原生 tool-call 循环（prompt_chat 分支 `max_loop`），编排 ck/pk 通用内核；task_chain/phase 为分形路由 a-f 分支，非独立「有界编排」。

### 11.4 记忆片段 / 数据面（预埋钩子驱动，最后实施）


- **复用 sl 既有机制（代码实证）**：
  - 永久区 = `session.permanent_system_prompt`（持久化于 `gateway.db` `session_snapshots`）+ `loaded_docs` 已加载文档（`context_router.py:45-59`）。
  - 记忆标签：`<user-memory>...</user-memory>`（`chat.py:593` `USER_MEMORY_PATTERN` → `_extract_user_memory` 提取内容写入永久区并剥标签继续 dispatch；`config.yaml:101` `session_memory.enabled`）。
  - 管理原语：`context_manager.load/unload/list/refresh`（按 `[tag]` 管理永久区）、`load_document`/`unload_document`（加载/卸载文档到永久上下文区）。
- **本片新增的唯一层 = 记忆 id 引用解析**（落 `build_messages` 预埋钩子处）：
  - **端口A（注入，复用 `load_document` 叠加 id 句柄）**：外部记忆服务 POST 记忆片段 → 写入永久区（落 `loaded_docs` 区）→ **返回 `memory_id`**。
  - **正式请求**：调用方用 sl 既有 `<user-memory>` 标签族包裹 id，扩展为 `<user-memory id="x"/>` 置入请求体（**仅带引用，不带内容**）。
  - **`build_messages` 解析**：扫描 `<user-memory id="x"/>` → 查永久区该 id 片段：命中 → 以 `loaded_docs` 形式展开为记忆文本注入；未命中 → **原样保留标签文本**进推理（优雅降级，不报错）。
  - **端口B（卸载，复用 `unload_document`/`context_manager.unload` 叠加 id）**：外部调用卸载指定 `memory_id` → 从永久区移除对应文档片段 → 后续不再注入。
- **为何不分裂**：`<user-memory id>` 是 sl 既有记忆标签的**同族扩展**，非新标签；永久区、load/unload 原语、标签所有权全部复用；仅新增「id 句柄 + 引用解析」一层。

### 为何此序
ck 是上下文与闸的基座；pk 相位依赖其装配与推理缝；sl 作为接线层把分形路由、闸组合、推理收束串起。先动 ck 保内核契约稳定，再 pk 统语义，最后 sl 接线——风险最低、回退最易；§11.4 记忆/数据面为终端片，依赖 11.3 在 `build_messages`/永久区/`load_document` 预埋的钩子，须最后实施。

---

## 附录 A：sl 预期架构草图（对齐基线 v3）

```
协议层 routers/
  chat.py            瘦身：保留请求级编排（pre-check/user-memory/packets/
                     相位路由/复杂度分类/分形路由决策），调 ck 做上下文装配+闸
  anthropic_chat.py 同构造（协议翻译入口）【本批冻结，待 OpenAI 主路径完成后再改造】
  pipeline.py       相位路径（pk 接管推理缝，sl 仅做协议/状态桥）

统一闸管理层（新增）
  services/gate_manager.py   对外暴露 ck/pk/未来闸；持有预制闸组合逻辑函数注册表，拥有跨内核循环

集成/收束层（新增）
  services/build_messages.py 单向收束其他分形产出（ck 提供装配消息，不回灌）
  integrations/context_kernel/
    runtime.py           CK 单例装配（读 vendored 文件夹）
    sl_session_source.py ContextSource（读 Session，persona 预组装）
    sl_inference_provider.py  LlmProvider（= sl_llm_provider，services/ 亦可）
    sl_data_plane.py     Phase artifacts（仅相位）
    pk_inference_seam.py pk 推理缝桥（Slice 3）

服务层 services/
  退役：context_router / context_injector / system_prompt_builder
        / asset_consumer / injection_pipeline
  保留下沉：downstream_llm / model_selector / streaming_handler
        / degradation_manager(strata侧) / context_manager(写方)
        / context_compressor(推送前 region 级 drop/compress, 同 ck 外挂示例逻辑) / tool_dispatcher / dynamic_tool_executor
  (sl_llm_provider 落此层，分叉2)

组件文件夹（vendored，热替换）kernels/
  context_kernel/   ← ck（G1–G2；G4 开放闸已实做于 ck，sl 仅对接；G5 修正为不持有分形路由）
  phase_kernel/     ← pk

执行面：textcli_enhanced_client + runtime_endpoints
策略面：strata_match_client（经 strata 侧 degradation）
持久化：database / config / models
```

### 三条请求流（集成后，入口统一为 chat.py handler）
> 所有请求从 `chat.py handler` 进入，由 sl 分形路由（复杂度分类 + 逻辑抽象 + `_is_phase_intent` + `_classify_by_fractal`）分派；相位只是其中一种特殊分形路由分支。

1. **单发主路径**：`chat.py handler → sl 分形路由 → ck.run_openai(body) → build_messages(收束) → sl_llm_provider → downstream`
2. **工具循环主路径**：`chat.py handler → sl 分形路由 → ck.run_openai(body)（推理收束层原样透传 tool_calls, 见 G3 必修复）→ sl 在 ck 完整响应上 tool_dispatcher 循环（含 ck.build_prompt 辅助装配）→ build_messages 收束`
3. **相位路径（特殊分形路由分支）**：`chat.py handler → sl 分形路由(识别相位意图, 特殊分形路由) → pk.phase_executor(经 sl.InferenceSeam 桥) → build_messages(喂 context_patch 为其他分形产出; 内部调 ck 取会话快照) → sl_llm_provider`

### 关键变化
- ck 为纯「**上下文管理 + 闸引擎**」内核（不持有分形路由）；暴露开放闸 HTTP 接口（get/set 钩子）。
- chat.py 保留请求编排（含分形路由决策），仅下沉上下文装配 + 闸给 ck。
- 推理收束唯一落点 = `sl_llm_provider`（services/）；上下文装配唯一落点 = ck（经 `sl_session_source`）。
- `gate_manager` 统一对外闸控；`build_messages` 收束异构分形产出（含 pk `InferenceSeam` 的 `context_patch`）；ck **单向**向 build_messages 提供会话快照装配（不回灌）。
- `context_*` 散落群退役。

---

_草案 v3.3 结束。**待裁决已清零**（#1–#6 全部已决）。v3.3 更正（模型分形家族化）：`tier` 从家族彻底出局——pk 改造点、pk 外挂字段、ck G1 的 tier 路径全部清零；pk 模型路由归属 pk 外挂服务（peer 外部服务，同 ck 外挂），其字段命名与语义双向对齐 sl 分形家族（sl 分形=正统叙事），愈合研发期分叉、合并须尽早；因无 `tier`，ck G1 不再背负 tier 转发僵尸路径、sl→ck→pk 边界少一脆弱点。v3.2 更正保留：G4 开放闸 ck 已实做（`core/gate.py`+`serve/server.py` park/peek/amend），从「待建」降为「sl 对接」；#6 `context_compressor` 落点 = 对 ck `region_index` 做 region 级变换（同 ck 外挂示例逻辑），置于 sl 推送前、模型窗口感知、不进 ck。_

_草案 v3.4：新增 §11.4（记忆片段/数据面，复用 sl 既有 `<user-memory>` 标签族与永久区 `permanent_system_prompt`+`loaded_docs` 装配，不新造 store / 不新造 `<sl-memory>` 标签），并在 §11.1–11.3 各片末尾预埋「供 §11.4 复用的钩子」，约束 11.1~11.3 实施不得破坏：记忆 id 引用解析单一落点、region 分区（`permanent`+`loaded_docs`）契约、`<user-memory>` 标签单一持有、`load_document`/`unload_document` 原语保留。_

---

## 附录 B：对 sl 新架构的认知（供对齐，v3.5）

> 本附录记录我对 sl 新架构的认知，逐条标注此前偏差与代码实证，供用户核验是否对齐。**核心更正：「编排网关」是错误认知。**

### B.1 认知偏差链（逐条被代码实证推翻）

| # | 我此前的表述（错） | 代码实证（对） | 出处 |
|---|---|---|---|
| 1 | 「LLM 网关」——把 sl 当中立透传 plumbing | sl 自持分形路由/模型选择语汇（`model_selector`+`llm_routing`+`complexity_classifier`+`execution_router`），是语义权威而非管道 | `src/app/services/*`、`config.yaml` |
| 2 | 「薄编排层是现状」 | 实为集成 **TARGET**；当前 sl 是 fat god-router（`chat.py` 依赖 28 模块） | 依赖图扫描（131 边） |
| 3 | 「sl 不是原生 tool-call loop」 | sl 内含真实 function-calling 循环：`for loop in range(max_loop)` → build_messages 暴露上下文+工具 → LLM 选工具 → `tool_dispatcher.execute` → 回灌 temp_history → 再循环 | `chat.py:383/389/398/402/417-425` |
| 4 | 「task_chain/phase 是有界编排（非分支）」 | task_chain/phase 是分形路由 a-f 分级下的**分支**（e/f→task_chain；相位为特殊分形路由） | `README_zh.md:101`、`api_zh.md:64` |
| 5 | ⚠ **「编排网关」** | **错误认知**——见 B.2 | — |

### B.2 ⚠ 「编排网关」是错误认知（关键更正）

- **sl 以 OpenAI/Anthropic 兼容 chat 接口对外暴露，这只是让 sl 更易被集成的形态（集成面），不是 sl 的本质/身份。** 把 sl 称为「网关」（gateway / pass-through plumbing）会误导：网关暗示 sl 是中立管道，而其真实身份是**分形叙事权威 + 内核编排器**。
- **正确表述**：sl = 「拥有家族分形叙事权威的分形编排控制面（fractal orchestration control plane）」；chat 接口 = 对外集成契约（兼容形态），便于别的 agent/客户端接入，**不构成 sl 的身份**。
- 推论：集成草案中**不应把「网关」当设计目标**——sl 的 chat 接口应保持兼容形态以易集成，但内核语义与编排权始终在 sl 内，不被外迁。

### B.3 sl 新架构的准确认知（代码实证）

1. **身份**：分形编排控制面。拥有家族分形叙事权威（路由/策略/模型选择语汇由 sl 定义，sl 分形=家族正统叙事）；编排 ck（上下文内核）+ pk（相位内核）+ peer 外挂（模型路由、记忆）为可替换件（经 data plane / 推理缝 / 闸交互）。
2. **内含原生 agent 循环**：prompt_chat 分支含 `for loop in range(max_loop)` 的 function-calling 循环（上下文暴露工具 → LLM 选工具 → sl 调工具 → 回灌循环）。故 sl 是「**被分形路由包裹的 agent**」，不是「非 agent」；「有界」只说明循环次数受控（max_loop 可配），不改变其 agent 本质。
3. **分形路由是上游决策层**：a/chat、b/prompt_chat、c/task、e/f/task_chain、相位——皆分形路由分支；分支选中后才进入对应执行（含 agent 循环）。
4. **集成形态**：组件文件夹 vendored（`kernels/` ck+pk），稳定适配层隔离；chat 接口兼容形态仅服务于外部集成（B.2）。
5. **记忆/数据面（§11.4）**：复用 sl 既有 `<user-memory>` + 永久区（`permanent_system_prompt`+`loaded_docs`），id 引用解析落 `build_messages` 钩子；不新造 store / 不新造 `<sl-memory>`。

### B.4 此认知对集成草案的含义

- ck/pk 是通用内核、被 sl 编排，不是 sl 的上级；sl 的「家族正统叙事」是内核语义对齐准绳（§11.2）。
- 改造次序 ck→pk→sl（§11）不变；sl 作为接线层把分形路由、闸组合、推理收束串起。
- 凡涉「sl 对外暴露形态」处，统一表述为「集成面（chat 接口兼容）」，不称「网关」；内核语义/编排权在 sl 内。

### B.5 对外价值外溢：让对接 agent 变薄，甚至薄成 SDK

- **sl 吞下复杂度**：分形路由 + 上下文装配（ck）+ 推理缝（build_messages）+ 模型选择语义（家族分形正统叙事）等子层全部收在 sl 内部、由 sl 编排。sl 越重（内核编排权越完整），下游越轻。
- **对接方无需自造这些子层（记忆除外）**：与 sl 对接的 agent 不必自己管上下文装配、不必自己写分形路由/模型选择；**记忆仍由 agent 维护**——区别在于可通过 sl 后续暴露的 API，按固定格式机械化注入记忆、再在 chat 中以引用（`<user-memory id>`）使用（§11.4）。它只需「发 chat 请求 + 注册工具/外挂（peer 外挂经闸/数据面交互）」。
- **可薄成一个 SDK**：由于 sl 以标准 OpenAI 兼容 chat 接口暴露（集成面，B.2），对接 agent 的接入成本极低，可瘦身为**一个仅封装 chat 调用 + 工具注册/回调的 SDK**。这与「编排网关」错误认知形成鲜明对照：sl 不是把复杂度透传给下游管道，而是**吞下复杂度、让下游变薄**。
- **推论**：B.2 的「chat 接口仅易集成」进一步外溢为产品价值——标准 chat 接口不但是集成形态，更是「对接方变薄、薄成 SDK」的使能器。sl 的产品化护城河不在「最 agent」，而在「让别人的 agent 最薄」；**「最自主」是模型厂商的叙事任务（见 B.6），sl 的叙事任务是 LLM 的实际执行度**——薄成 SDK 正是为了让别人在自己的执行场景里把 LLM 跑好。

### B.6 叙事立场：自主 loop = 模型厂商叙事 / 路由+上下文 = LLM 实际执行度叙事

- **「自主 loop」是模型厂商的叙事**：「模型能自主干活」卖的是模型能力本身——loop 越长、工具调用越自主，越显模型聪明、越扩大调用面、越能卖 token/订阅。主流 agent 框架（尤其模型厂商自家 agent SDK）拼命推自主 loop，深层动机是让模型成为执行主体。这是**上游供给侧的叙事**。
- **「路由 + 上下文内核」是 LLM 实际执行度的叙事**：分形路由 = 把对的事路由给对的规格；上下文内核（ck）= 把对的内容装进窗口；成本意识 = 不浪费每一轮调用；薄成 SDK = 让别人在自己的场景把 LLM 跑起来。全部指向一个目标——**LLM 在真实业务里能否稳定、可控、省成本地执行**。这是**下游使用侧的叙事**，关心 execution degree，不关心 model capability 的炫技。
- **由此修正此前的对比框架**：此前以「局部领先/整体不领先」做工程对比的口径**不成立**——自主 loop 与 路由+上下文 不是同一维度的强弱比，而是**两套服务于不同对象的叙事**。sl 不是「在自主叙事上弱」，而是**根本不在模型厂商的叙事场上**；其场是「LLM 的实际执行度」。
- **统一轴**：分形成本意识、上下文内核化、薄成 SDK 等此前被当独立优点的设计，在此收口为**一条轴——一切为了 LLM 的实际执行度**。这比「薄成 SDK」的价值描述更本质：薄成 SDK 是手段，执行度叙事才是立场。

---

_草案 v3.5：新增附录 B（对 sl 新架构的认知，供对齐）。明确指出「编排网关」是错误认知——sl 以 OpenAI 兼容 chat 接口对外暴露仅是让 sl 更易被集成的形态（集成面），非 sl 本质；sl 本质=拥有家族分形叙事权威的分形编排控制面，内含原生 tool-call 循环（prompt_chat 分支 max_loop），编排 ck/pk 通用内核；task_chain/phase 为分形路由 a-f 分支。B.1 完整列出此前五条偏差及代码实证出处。_

_草案 v3.6：附录 B 新增 B.5「对外价值外溢：让对接 agent 变薄，甚至薄成 SDK」——sl 把分形路由+上下文装配+推理缝+模型选择等重活收在内部（记忆仍由 agent 维护，仅经 sl 暴露的 API 按固定格式机械化注入/引用，§11.4），对接方无需自造这些子层、可瘦身为仅封装 chat 调用+工具注册的 SDK；标准 chat 接口既是易集成形态、也是「对接方变薄」的使能器；与「编排网关」错误认知对照，sl 吞下复杂度而非透传。顶部状态块同步 v3.5/v3.6。_

_草案 v3.7：附录 B 新增 B.6「叙事立场：自主 loop = 模型厂商叙事 / 路由+上下文 = LLM 实际执行度叙事」——否定「局部领先/整体不领先」的工程对比口径，明确两套叙事服务于不同对象（上游供给侧 vs 下游使用侧），sl 不在模型厂商叙事场、其场是 LLM 实际执行度；并修正 B.5 推论句（「最自主」是模型厂商叙事任务，sl 叙事任务是 LLM 执行度）。顶部状态块同步 v3.7。_
