# context-kernel 概念策划（ck 作为 sl 主路径"上下文管理核心 + 闸引擎"的专项展开）

> 性质：概念讨论件（concept）。非设计文档（设计真源见 `design_zh.md`）、非版号发布件。
> **未发布·无正式版号**：ck 尚未对外发布，本文档不挂任何 release 版本号，仅以日期 + 对齐基线标记演进。
> 日期：2026-08-23
> 对齐基线：`integration_sl_draft_zh.md` v3.7（sl 集成 ck/pk 总纲草案）+ `concept_V0_1_2_b_zh.md`（sl 侧组件文件夹 vendored 展开）
> 来源：`other/context-kernel/docs/design_zh.md`、`other/context-kernel/docs/integration_sl_draft_zh.md` §11.1
> 定位：本件是「ck 视角」专项概念——把 integration 草案 §11.1（ck 先行的改造片）从 ck 内核立场重述，
>       锁定 ck 的责任边界与待改项，与 sl 侧 `_b` 概念互为表里（sl 说"我要 vendored 你、喂你快照、聚合你的闸"，
>       ck 说"我内核为此改什么、不改什么、守什么"）。
> **文档角色**：本件是「研发计划（dev-plan）」文档的**前置概念件**——不替代 dev-plan、不固定实现顺序，
>       只把待决项细化为**可供最终决策的判断依据**（含选项 / 事实 / 影响 / 风险 / 推荐），待用户拍板后由 dev-plan 承接落地。

---

## 〇、与 sl `_b` 概念的关系

- sl `_b` 概念 = 「sl 集成 ck/pk 的组件文件夹 vendored 展开方案」（sl 侧视图）。
- 本件 = 同一集成工作的 **ck 内核侧对应展开**。两者是同一集成工作的两个视图，非前后两件事。
- 本文档不重复 ck 已实现细节（见 `design_zh.md`），只聚焦于「集成视角下 ck 要动 / 不动 / 守约」三项。

---

## 一、ck 的本质定位（在 ck→pk→sl 三核体系中的角色）

- **ck = 推理闸内核 + 上下文管理核心**：在「拼装完成」与「推模型」之间插入可干预点，让上下文推模型前可见/可改/可放过，且干预绝不回写会话（设计 §1.1）。
- **ck 是体系基座**：pk 相位依赖 ck 的装配与推理缝，sl 最后把三者接线（改造次序 ck→pk→sl）。
- **ck 是通用态内核**：可 standalone、零上游依赖、接不接 sl 都自洽；协议与 pk 对齐（context_id 统一令牌、错误码闭集、双形态），但实现独立、不互相依赖。
- **ck 非网关、非路由权威**：不持有分形路由、不持有模型选择语义、不持有学习环——这些归 sl（sl 分形 = 家族正统叙事）。
- **设计纪律**：sl 重活收在 sl 内，ck 保持通用；ck 只暴露钩子，不拥有学习环。

---

## 二、§11.1 对 ck 的更新（本件核心）

### 2.1 G1 — model 转发（ck 需改）
- 现状：ck 忽略 `body["model"]`，仅用 `self.primary_model`；`fallback_model` 零引用；`ext.tier` 已不存在（tier 出局）。
- 更新：`run_openai` 提取 `body["model"]`（+ `ext["service_name"]`），透传 `chat(messages, model, stream, service_name=)`。
- 落点（vendored ck 文件夹）：`context_kernel.py:157-158` 与 `194-195` 两处 `llm_provider.chat(..., self.primary_model, stream=False)`。
- 语义收口：ck 对模型意图**透明转发**——模型选择语义归 sl 分形家族，ck 不决策、不内嵌。`tier` 已出局故不再处理，内核更轻、sl→ck→pk 边界少一处静默错配脆弱点。
- **⚠ G1 端口签名待决（见 §七 D1）**：当前 `ports/__init__.py:57` 的 `LlmProvider.chat(messages, model, stream)` **无 `service_name` 参数**。是否扩签名，决定 ck 是否持有 service 路由意识——属待决项，本件给依据不代决。

### 2.2 G2 — 流式分支（ck 需改）
- 现状：`stream=False` 硬编码于同上两处。
- 更新：`run_openai` 读 `body["stream"]`，为真时返回流而非 `InferenceResult`。
- 落点：同上两处。

### 2.3 G4 — 开放闸 HTTP（ck 已实做，无需改）
- v3.2 更正：`core/gate.py`（`gate_get/gate_set`）+ `serve/server.py`（park/peek/amend）**已落地**。
- §11.1 结论：ck 对 G4 **零改动**；sl 侧 `gate_manager` 仅对接消费该 HTTP 协议并聚合对外。
- 关键厘清：结构化 `GateResponse` + 预制组合函数注册表 + 跨内核循环属 **sl `gate_manager`**（sl 侧高层设计），**非 ck 职责**。ck 只提供通用闸原语（开闭态 + 结构化闸响应）+ 单内核通用闸引擎。
- 后果：ck 保持零 sl 依赖、可 standalone。

### 2.4 G5 — ck 不持有分形路由（ck 无需改，仅暴露钩子）
- §11.1：ck **不新增分形路由**。分形决策（取 sm prompt / 选模型规格等）归 sl 上游，经 `build_messages` 产出初始上下文后进 ck。
- ck 在**开闸态暴露 `get/set` 可编程钩子面（HTTP）**——`gate_mode=open` 时供 sl 之外的外挂改进服务读取分形决策 + ck 装配上下文、回写改进、记循环提升 sm 策略。
- 学习环归外挂服务（out-of-scope），ck 不实现。开闸态钩子是**可选暴露**，不接不影响内核。

### 2.5 G3 — tool_calls 透传（ck **必须修**·原措辞"丢弃"是概念错误）
- **原措辞错误（v3 及之前）**：此前写「ck 只返 content、丢 tool_calls、sl 工具循环走 `build_prompt`+`sl_llm_provider` 绕开 ck」——这把 ck 降级成旁路，**与「分形全部走 ck、ck 是 sl 主路径上下文管理核心」的定调自相矛盾**。
- **事实修正（用户定调 2026-08-23）**：分形全部走 ck → ck 的 LLM 收束层必须**完整透传 tool_calls** → sl 在 ck 返回的完整响应上做工具调度循环。ck 的返回塑形层（`_assemble_and_gate` 的 closed `:157-166` 与 gate_set `:194-197` 两处只剥 `content`）**本质是阻断了 sl 经 ck 调工具**——这是 ck 的真实缺陷，不是"不改"项。
- **处置（G3 必须修）**：`InferenceResult` 增加 `tool_calls` 字段，从 `response["choices"][0]["message"]["tool_calls"]` 原样透传；closed 与 gate_set 两处返回层都补提取；sl 侧 `build_messages`/`sl_llm_provider` 拿到 ck 完整响应后按 tool_calls 是否存在进入工具循环（sl 职责，不归 ck）。
- **对 ck 外挂 `serve/` 的影响**：`serve/server.py` 的 envelope（closed `:166-171` + gate_set `:201-206`）当前只塞 `content`/`ext`，**须同步透传 `tool_calls`**（含 `CK_SCHEMA.outputs` 补声明），否则独立外挂也吃不到工具调用。属 §九 E 序列新增等同修正项（见 §九 E5）。
- 落点：`core/models.py`（`InferenceResult` 加字段）+ `core/context_kernel.py:157-166`/`:194-197`（两处提取）+ `serve/server.py`（两处 envelope + schema）。

### 2.6 ⚠ 预埋钩子（供 §11.4 记忆/数据面复用，ck 侧不得破坏）
- ck 的 `region_index` 分区（`session_id/permanent/loaded_docs/client_system/temp/current`）须保持为**规范契约**，不得合并/重命名区域。
- §11.4 的记忆片段将解析进 `loaded_docs` 区；若本件 G1/G2 改动触及 region 语义，须同步通知 §11.4。

---

## 三、§11.1 不要求 ck 改什么（边界守则）

- 六层拼装（layered）：不变。
- 推理闸两段流（park/peek/amend）：不变。
- `gate_mode × context_mode` 正交：不变。
- 红线①-⑦：全部保留（尤其④会话写权在 serve 层、⑥闸绝不回写会话、⑦闸逻辑单点）。
- ck standalone 能力与零上游依赖：保留。
- 闸语义仍由 ck 自持：sl `gate_manager` 只编排/组合/对外暴露，不接管 ck 闸语义。

---

## 四、ck 与 sl `build_messages` 的收敛关系（重申，防错位）

- ck **是 sl 主路径的推理收束载体**（分形全部走 ck）——ck 的 LLM 收束层原样返回 LLM 完整响应（`content` + `tool_calls` + `usage`，见 §2.5 G3），sl 在 ck 完整响应上做工具调度循环。
- ck **不是** `InferenceSeam` 直接落点；ck 是 `build_messages` 的**内部依赖**（取会话快照装配 + 持有推理收束）。
- ck **单向**向 `build_messages` 提供基于会话快照的装配消息（不回灌）；会话状态归 sl（`SessionManager`/`context_manager`）。
- 所有路径最终收敛到唯一推理收束点 `sl_llm_provider`——但 `sl_llm_provider` 在蓝图里经 ck 的 LLM 收束层取得完整响应（含 tool_calls），**不是绕开 ck 直连 LLM**（旧 §2.5 措辞的误区已更正）。
- pk 相位经 `InferenceSeam.infer(context_patch)` → `build_messages`（内部调 ck 取快照 + 推理收束）→ `sl_llm_provider`；ck 不直接被 pk 依赖，藏在 sl 的 `build_messages` 内部（组件隔离：pk 只认缝，不认 ck）。

---

## 五、集成形态（组件文件夹 vendored）

- ck 以 vendored 文件夹集成进 sl：`src/app/kernels/context_kernel/`（纯副本，热替换整体替换）。
- sl 只 `import` ck 公开 API（`from context_kernel import ContextKernel`），绝不 import 内部子模块。
- ck 的 G1/G2 改动落在 vendored 副本；待 ck 上游发布新版，sl 直接整体替换文件夹，稳定适配层（`sl_session_source`/`sl_inference_provider`/`sl_data_plane`）对齐公开 API 即可。
- 稳定适配层隔离：ck 内部变更不波及 sl。

---

## 六、ck 自身待实施改造清单（细化·供 dev-plan 承接）

> 本件是概念前置件，不直接落盘改代码；以下把每项改造的**精确代码落点 + 动作**列清，作为 dev-plan 的任务拆分依据。

### 6.1 去 tier 修复（ck 侧·低风险）
**事实依据**：ck 的 `Tier` 纯透传僵尸字段——`models.py:8` 注释已声明「tier 仅作透传元数据，不决模型」，代码逻辑**全不消费** tier 值（无 `if tier==` 分支）。去 tier 只是删透传壳。

| 文件 | 行 | 当前 | 动作 |
|---|---|---|---|
| `core/models.py` | 18-26 | `class Tier(str, Enum)` 定义 | **删除整段** |
| `core/models.py` | 77 | `ContextPatch.tier: Optional[Tier] = None` | **删除字段** |
| `core/models.py` | 85 | `to_dict` 中 `"tier": self.tier.value if ...` | **删除该键值** |
| `core/models.py` | 91-92 | `from_dict` 中 `tier_raw` / `Tier(tier_raw)` | **删除解析** |
| `__init__.py` | 13, 31 | `Tier` 导入 + `__all__` 导出 | **删除两处** |

**影响**：`ContextPatch` 修订为 `{phase_path, intent, context_id, ext}`（与 §11.1 "tier 出局" 一致）。`design_zh.md` §3.3/§6.1 的 `tier`/`Tier` 描述需同步回写（属设计文档修订，不在此件范围）。
**风险**：极低。无调用方依赖 tier 值；唯一外部消费者是 pk `ContextPatch`（pk 侧去 tier 见 §八，需同步）。

### 6.2 G1 model 转发（ck 侧·需改·落点精确）
- `context_kernel.py:157-158`（closed 直推）、`:194-195`（gate_set 修正推）两处：
  `self.llm_provider.chat(assembled.messages, self.primary_model, stream=False)`
  → 改为从 `body` 提取 `model`（+ `service_name`，见 §七 D1 决策）→ 传参。
- `run_openai` 已解析 `body`（`:63-97`），`model`/`stream` 可直接从 `body` 取，无需改签名。
- **HTTP 层 `server.py` 无需动**：`run_openai` 内部吸收 `body["model"]` 即可。

### 6.3 G2 流式分支（ck 侧·需改·同落点）
- 同上两处 `stream=False` 硬编码 → 读 `body["stream"]`，为真返流（`yield` / `StreamingResponse` 等价物）。
- 注意：`gate_set`（`:194-195`）的流式语义需确认——开闸修正推是否也走流？建议与 D1 一并决策。

### 6.4 G4 开放闸（零改动·已就绪）
- `gate.py` + `server.py` park/peek/amend 已落地；`CK_SCHEMA.gate_protocol` 已声明协议。sl `gate_manager` 对接消费即可。

### 6.5 region 契约守约（不改·预埋）
- `gate.py:64` 六区 `session_id/permanent/loaded_docs/client_system/temp/current` 锁死；`loaded_docs` 为 §11.4 记忆落点，G1/G2 改动不得触碰 region 语义。

### 6.6 G3 tool_calls 透传修复（ck **必须修**·概念错误纠正，见 §2.5）
> 原 v3 把 G3 列为「不改」是概念错误——分形全部走 ck，ck 返回层丢 tool_calls 等于阻断 sl 经 ck 调工具。用户已拍板 G3 必须修。

| 文件 | 行 | 当前 | 动作 |
|---|---|---|---|
| `core/models.py` | `InferenceResult` 定义 | 仅 `content` / `context_id` / `result_ref` / `ext` | **加 `tool_calls` 字段**（默认 `None`）|
| `core/context_kernel.py` | 157-166（closed 直推） | `content = response[...]["message"]["content"]` | **补 `tool_calls = response[...]["message"].get("tool_calls")`** 一并入 `InferenceResult` |
| `core/context_kernel.py` | 194-197（gate_set 修正推） | 同上只剥 content | 同上补 `tool_calls` |
| `serve/server.py` | 166-171（closed envelope） | 只塞 `content`/`ext` | **补 `tool_calls` 透传**（None 时省略键）|
| `serve/server.py` | 201-206（gate_set envelope） | 只塞 `content`/`ext` | 同上补 `tool_calls` |
| `serve/server.py` | 79-102（CK_SCHEMA） | `outputs` 仅 `content`/`context_id` | **`outputs` 补 `tool_calls: "list|null"`** |

**影响**：sl 工具循环经 ck 完整响应（含 `tool_calls`）驱动，ck 不再阻断；ck 独立外挂 `serve/` 也原样透传 `tool_calls`，可独立驱动工具循环。
**风险**：低。仅加法字段（默认 None），旧调用方不消费 `tool_calls` 时 envelope 省略该键，零破坏。
**落地归属**：本件 dev-plan 的 Phase 2.6（新增，见 development-plan_ck_zh.md）。

---

## 七、ck 侧待决/开放项 → 最终决策依据表

> 本表为**待用户拍板**项。每项列「选项 / 事实依据 / 影响 / 风险 / 推荐」，供最终决策；本件不代决。

### D1 — G1 端口签名是否扩 `service_name`（影响 tier 语义统一落点）
| 维度 | 内容 |
|---|---|
| **事实依据** | `ports/__init__.py:57` `LlmProvider.chat(messages, model, stream)` 无 `service_name`；`run_openai` 的 `body` 已有 `ext["service_name"]` 槽（`:75`）但未用；sl 分形家族的模型路由语义含「service 维度」（不只是 model 名）。 |
| **选项 A** | 扩签名 `chat(messages, model, stream, service_name=None)`——ck 透传 service 意识，sl `sl_llm_provider` 据此路由。 |
| **选项 B** | 不扩签名，仅透 `model`；service 路由完全收在 sl 侧（`sl_llm_provider` 内部解析 model 隐含的 service）。 |
| **影响** | A：ck 端口契约变更，vendored 适配层需同步；但语义更显式、sl→ck 边界更清晰。B：ck 保持极简，但 model 字符串需编码 service 信息（约定俗成，易静默错配）。 |
| **对 ck 外挂服务的影响** | G1 改动**直接增强** ck 独立 `serve/` 服务的多模型能力（此前外挂只能跑 `ck-primary` 硬编码，改后可按请求 `body["model"]` 选模型）。但需同步：① `CK_SCHEMA` 声明 `model`/`stream` 透传契约（否则外部调用方无据）；② `make_kernel`/`build_app` 的 `primary_model` 语义从「唯一模型」退为「缺省模型」（`:52`/`:214`）；③ `server.py` 不改逻辑（已透传 `body` 给 `run_openai`），仅补 schema。 |
| **风险** | A：pk 侧 `LlmInferenceReceiver` 若复用同一 `LlmProvider` 协议需同步改（见 §八）。B：model 字符串耦合 service，违反「单一真相来源」纪律。 |
| **推荐** | **A**——显式优于隐式；与「模型选择语义归 sl 分形家族、ck 透明转发」的收口一致；service 作为一等参数比塞进 model 字符串更可持续。 |
| **✅ 已决（用户拍板）** | **采纳 A**：扩 `chat(messages, model, stream, service_name=None)`。补充约束：**`service_name` 不传（None）时按 ck 既有默认行为回落**（即不强制传参，缺省即默认 service/model），保障 ck 外挂与旧调用方零破坏（见 §九 E2 语义降级）。 |

### D2 — pk 去 tier 后的相位阶段语义承载（核心战场·见 §八细化）
| 维度 | 内容 |
|---|---|
| **事实依据** | pk 的 `InferenceTier` **非透传**——`inference_receiver.py:56-61` 用 tier 选三套系统提示词（规划器/执行器/摘要器）；`orchestrator.py:149/491/825` 三处 `context_patch(tier=...)` 驱动 planning/normal/summary 三阶段分支。pk 的 tier = 相位生命周期阶段标识。 |
| **选项 A** | pk 内核**保留**阶段标识，但改名为 sl 分形家族词汇（如 `phase_stage=planning|executing|summarizing`），字段归属 pk 内核、语义对齐 sl 叙事。 |
| **选项 B** | pk 内核**去除**阶段标识，改由 `phase_path`（已有字段）隐含阶段；系统提示词路由改按 `phase_path` 末段判断。 |
| **选项 C** | pk 内核去 tier，阶段语义**上移至 sl 分形路由**——sl 在 `build_messages` 前已决定「本次推理属规划/执行/摘要」，经 `ext` 槽传入 pk，pk 不持有阶段概念。 |
| **影响** | A：pk 内核仍自持阶段语义（最小改动，但 pk 仍背阶段词汇，未完全愈合）。B：pk 最轻，但 `phase_path` 隐含阶段脆弱（路径结构变更即断）。C：最契合「sl 分形 = 正统叙事、内核只做一件事」，但 sl 需新增阶段决策点。 |
| **风险** | A：未彻底愈合分叉，后续仍两套词汇并存。B：`phase_path` 结构耦合提示词路由，违反稳定契约。C：sl 改造面最大（需在 `build_messages` 前插入阶段决策）。 |
| **推荐** | **C** 为长期目标；**A 为过渡**（先改名对齐词汇、内核仍持，待 sl 侧 `build_messages` 阶段决策成熟再上移）。需用户在「过渡 A」与「一步到位 C」间拍板。 |
| **✅ 已决（用户拍板·重新定性）** | **采纳 C 方向，但定性修正**：planning/normal/summary 三阶段**不是「分裂/分叉」，而是 sl 模型分形家族新增的三种类型**——这是对家族的**增强/扩充**，不是背离。即：sl 分形家族从原有类型扩充出「规划型/执行型/摘要型」三类模型分形，pk 内核不再自持阶段标识，改由 sl 在 `build_messages` 前按家族类型决策，经 `ext` 或显式字段传入 pk。措辞上全件「愈合分叉」一律改为「家族类型扩充」。 |

### D3 — pk `tier→model` 路由表归属（与 D1 联动）
| 维度 | 内容 |
|---|---|
| **事实依据** | `inference_receiver.py:28` 注释：「tier→model 路由表由调用方（装配处）持有；本接收器只负责拼装 + 调用 + 回填」——即 pk 已声明**不持有** model 路由，归调用方。 |
| **选项 A** | 路由表归 **pk 外挂服务**（与 ck 外挂同构的 peer），不归 pk 内核、不归 sl——pk 外挂字段/语义双向对齐 sl 分形家族。 |
| **选项 B** | 路由表归 **sl 分形路由**（sl 在 `build_messages` 前选好 model，经 `body["model"]` 透传 pk→ck→sl_llm_provider）。 |
| **影响** | A：符合「模型路由不进内核」纪律，pk/ck 外挂对称；但多一个外部服务。B：sl 集权，但 sl 需同时管 pk 与 ck 的 model 透传。 |
| **风险** | A：外挂服务若未就位，pk 相位推理无 model 来源（需默认壳）。B：sl 耦合 pk 相位 model 细节。 |
| **推荐** | **A**——与「pk/ck 外挂同构、内核零模型语义」架构一致；sl 分形家族通过外挂字段命名对齐（含 D2 三类型收纳）。 |
| **✅ 已决（用户拍板）** | **采纳 A**：`tier→model` 路由表归 **pk 外挂服务**（与 ck 外挂同构 peer），内核零模型语义；pk 外挂字段命名 + 模型选择语义双向对齐 sl 分形家族（含 D2 新增的三种类型）。 |

### D4 — ck 去 tier 与 pk 去 tier 的协同时序
| 维度 | 内容 |
|---|---|
| **事实依据** | ck `ContextPatch` 与 pk `ContextPatch` 字段需对齐（integration 草案四缝契约）；两处都去 tier 后，`ContextPatch` 收敛为 `{phase_path, intent, context_id, ext}`。 |
| **选项 A** | **先 ck 后 pk**（ck 去 tier 低风险、可独立验证；pk 去 tier 涉及阶段语义需 D2 先决）。 |
| **选项 B** | 同步去（两处同版次 vendored 替换，避免中间态契约错位）。 |
| **影响** | A：ck 先行降低整体风险，但 pk 未决前 sl 集成契约为「ck 无 tier / pk 有 tier」暂态。B：契约一步到位，但 pk D2 未决前无法启动。 |
| **风险** | A：暂态契约需 sl 适配层兼容两种 `ContextPatch`。B：阻塞在 D2 决策。 |
| **推荐** | **A**（ck 去 tier 立即可做；pk 去 tier 等 D2 拍板后做）。 |
| **✅ 已决（用户拍板）** | **采纳 A**：先 ck 后 pk。ck 去 tier 立即可做（低风险）；pk 去 tier 等 D2 定性（家族类型扩充）落地后做，pk 外挂路由表（D3）同步就位。 |

### D5 — G2 流式在 gate_set（开闸修正推）的语义
| 维度 | 内容 |
|---|---|
| **事实依据** | `context_kernel.py:194-195` gate_set 也调 `chat(..., stream=False)`；开闸态修正推是否需流式未定义。 |
| **选项 A** | gate_set 也读 `body["stream"]`（与 closed 一致）。 |
| **选项 B** | gate_set 恒为非流（修正推为单点结果，外挂消费无需流）。 |
| **影响** | A：一致性强。B：外挂 amend 拿完整结果更简单。 |
| **风险** | A：流式 amend 的 park 生命周期管理更复杂。 |
| **推荐** | **B**（gate_set 恒非流，降低开闸态复杂度；流式仅用于 closed 主路径）。 |
| **✅ 已决（用户拍板）** | **采纳 B**：gate_set（开闸修正推）恒为非流；流式仅用于 closed 主路径。 |

### 已决项汇总（用户拍板·截至 v3）
**来自 §11.1 / integration_sl_draft（无需再决）**：
- G1 model 转发（落点已锁）、G2 流式、G4 已实做不改动、G5 不持分形路由、region 契约守约、vendored 集成、context_compressor 落点归 sl（不进 ck 内核）、gate_manager 高层设计归 sl。
- **G3 原列「不改」系概念错误，已翻转（用户拍板 2026-08-23）**：分形全部走 ck，ck 返回层丢 tool_calls 阻断 sl 经 ck 调工具 → **G3 必须修**（见 §2.5 / §6.6 / §九 E5）。

**来自本件 D1–D5（用户拍板）**：
- **D1 ✅**：扩 `LlmProvider.chat(..., service_name=None)`；不传则按 ck 默认回落（零破坏旧调用方）。
- **D2 ✅**：pk planning/normal/summary 定性为 **sl 模型分形家族新增三种类型**（增强/扩充，非分裂）；内核不再自持阶段标识，改由 sl 在 `build_messages` 前按家族类型决策传入（采纳 C 方向）。
- **D3 ✅**：`tier→model` 路由表归 **pk 外挂服务**（与 ck 外挂同构 peer），内核零模型语义，字段对齐 sl 分形家族（含 D2 三类型）。
- **D4 ✅**：时序 = **先 ck 后 pk**（ck 去 tier 立即可做；pk 去 tier 等 D2/D3 就位后做）。
- **D5 ✅**：gate_set 恒非流；流式仅用于 closed 主路径。

---

## 八、pk 去 tier 探查细化与家族类型扩充映射（D2/D3 的判断依据）

### 8.1 pk 的 `InferenceTier` 嵌入口全清单
| 文件:行 | 角色 | tier 消费方式 |
|---|---|---|
| `core/models.py:300-327` | `InferenceTier` 枚举 + `ContextPatch.tier` 字段（默认 NORMAL）+ 序列化 | 数据结构载体 |
| `core/orchestrator.py:149` | `context_patch(tier=PLANNING)` 顶层规划 | **路由键**：走 planning 分支 |
| `core/orchestrator.py:491` | `context_patch(tier=NORMAL)` 相位执行 | **路由键**：走 normal 分支 |
| `core/orchestrator.py:825` | `context_patch(tier=SUMMARY)` 浓缩 | **路由键**：走 summary 分支 |
| `serve/inference_receiver.py:56-61` | `tier→system_prompt` 映射表 | **实际消费**：选三套提示词 |
| `serve/inference_receiver.py:74` | `_mechanical_content` 按 tier 分支 | 机械兜底分支 |
| `tests/test_inference_seam.py` | 断言 tier 为「骨架字段」 | 测试强耦合（去 tier 必改测试） |

### 8.2 关键判断：pk 的 tier ≠ ck 的 tier
- **ck tier**：纯透传僵尸字段，逻辑零消费 → 去之零风险（§6.1）。
- **pk tier**：**相位生命周期阶段标识**（planning/normal/summary = 规划/执行/摘要三阶段），被 `orchestrator` 三处路由 + `inference_receiver` 提示词映射**实际消费**。
- **去 pk tier 的本质（用户重新定性）** = sl 模型分形家族**新增三种类型**——planning/normal/summary 不是对家族的「分裂/分叉」，而是**对家族的增强与扩充**：sl 分形家族从原有类型扩充出「规划型/执行型/摘要型」三类模型分形。pk 内核不再自持阶段标识，改由 sl 在 `build_messages` 前按家族类型决策，经 `ext` 或显式字段传入 pk。这正是「tc 家族以 sl 为代表的模型分形使用的语义统一」——统一的方向是**家族收纳新类型**，而非消灭差异。

### 8.3 家族类型扩充映射方案（对应 D2 已决·C 方向）
| pk 现状（tier 消费点） | 旧语义：阶段标识 | 新语义：sl 分形家族三类模型分形（扩充） | sl 决策点 |
|---|---|---|---|
| `orchestrator:149` planning | 顶层规划阶段 | **规划型**模型分形（生成相位计划） | sl 在 `build_messages` 前按家族类型选「规划型」，经 `ext.model_type=planning` 传入 |
| `orchestrator:491` normal | 相位执行阶段 | **执行型**模型分形（生成相位产物） | 同上，`ext.model_type=executing` |
| `orchestrator:825` summary | 浓缩阶段 | **摘要型**模型分形（低 b 浓缩上下文） | 同上，`ext.model_type=summarizing` |
| `inference_receiver:56-61` 提示词 | 按 tier 选三套 | 按 `ext.model_type` 选三套（字段名对齐家族词汇） | pk 不持类型语义，纯按传入字段选提示词 |
| `tests` 断言 | tier 为骨架字段 | 改为断言 `ext.model_type` ∈ {planning,executing,summarizing} | 测试随字段迁移 |

> 注：字段名 `ext.model_type` 为暂定，最终命名须在 pk 改造早期与 sl llm_routing 词汇对齐（D3 外挂字段双向对齐）。核心是**类型归属 sl 家族、pk 仅按传入字段路由**，pk 内核零类型语义。

### 8.4 pk 外挂字段对齐 sl 分形家族（D3 已决落地）
- pk 外挂服务（peer of ck 外挂）承接模型路由表（`inference_receiver.py:28` 已声明归调用方）。
- 外挂字段命名 + 模型选择语义**双向对齐 sl 的 llm_routing 词汇**（sl 侧：`complexity`/`fractal`/`model_selector`/`execution_router`，6 场景 model_config.yaml）；**D2 新增的三种类型（规划/执行/摘要）同样纳入家族词汇对齐**。
- 这不是「合并分叉」，而是**家族收纳**：pk 外挂作为 sl 分形家族在 pk 侧的承载点，字段语义本就是家族语——研发期曾用 `tier` 暂名，现正名为家族类型。draft v3.3 已决：tier 从 pk 改造点/外挂/G1 路径全清零，正名为家族类型。

---

## 九、ck 外挂服务独立性评估与同等修正（用户关切：改动是否影响 ck 自身外挂）

> 用户定调：须审视 ck **自身 standalone 外挂服务**（`context_kernel/serve/`）的独立性——
> 前述 G1 / 去 tier 改动是否冲击 ck 外挂、若冲击须做何种**同等修正**。

### 9.1 ck 外挂服务独立性现状（serve/ 全盘点）
| 文件 | 角色 | tier 残留 | model 路由 |
|---|---|---|---|
| `serve/server.py` | 独立 HTTP 服务（`ThreadingHTTPServer`，零 sl 依赖） | **无**（未 import `Tier`，未引用 `tier`） | 单模型硬编码：`make_kernel`/`build_app` 默认 `primary_model="ck-primary"`（`:52`/`:214`）；`run_openai` 忽略 `body["model"]` |
| `serve/session_store.py` | 会话存储（永久区+临时窗口+loaded_docs） | **无** | 无关（纯存储） |
| `CK_SCHEMA`（server.py:79-102） | 对外协议声明 | 未声明 tier | **未声明 `model`/`stream` 透传** |

**独立性结论**：
- ck 外挂服务**零 sl 依赖**、可独立 `python -m context_kernel.serve.server` 部署，是通用推理闸服务。
- **去 tier 对 ck 外挂 = 零冲击**：`serve/` 从未 import/消费 `Tier`；`tier` 仅存在于 `ContextPatch` 数据结构内部（pk 组件形态用，sl vendored 用），外挂服务的三个端点（`run_openai`/`gate_get`/`gate_set`）签名都不带 tier 参数。删 `Tier` 枚举 + `ContextPatch.tier` 字段后，`serve/` **无需任何修改**（验证：`server.py` import 清单 `:29-33` 不含 `Tier`）。
- **G1 对 ck 外挂 = 正向增强但需契约补全**：G1 让 `run_openai` 透传 `body["model"]`，外挂服务由此从「只能跑 `ck-primary`」升级为「按请求选模型」——这是能力增强，非破坏；但当前 `CK_SCHEMA` 未声明该能力，外部调用方无从知晓。

### 9.2 同等修正清单（ck 外挂服务侧）
| # | 修正项 | 文件:行 | 动作 | 性质 |
|---|---|---|---|---|
| E1 | `CK_SCHEMA` 补 `model`/`stream` 透传声明 | `server.py:79-102` | 在 `envelope` 或新增 `request_contract` 段声明 `body.model`/`body.stream` 透传语义（缺省回落 `primary_model`） | 契约补全（非逻辑改动） |
| E2 | `primary_model` 语义降级声明 | `server.py:52,214` + `context_kernel.py:34-43` | 注释/文档明确 `primary_model` 从「唯一模型」退为「缺省模型」（请求未带 `model` 时回落） | 语义澄清 |
| E3 | `make_kernel`/`build_app` 参数透传校验 | `server.py:48-63,210-226` | 确认 `body["model"]` 透传链：`server.py:160` 已整包传 `body` 给 `run_openai` → `run_openai` 内部取 `model`（G1 落点）；`server.py` 本身**不改逻辑**，仅确保 `body` 不被裁剪 | 验证项（预计零改动） |
| E4 | 去 tier 后 `serve/` 回归测试 | `tests/test_serve_smoke.py` | 确认 `serve` 导入链不含 `Tier`（删 `Tier` 后冒烟测试须仍绿） | 测试保障 |
| **E5** | **G3 `tool_calls` 透传（serve 侧等同修正）** | `server.py:166-171`（closed envelope）、`:201-206`（gate_set envelope）、`:79-102`（CK_SCHEMA） | **envelope 两处补 `tool_calls` 透传**（None 时省略键）；`CK_SCHEMA.outputs` 补 `tool_calls: "list|null"` | 逻辑补充（G3 修复的 serve 侧落地） |

### 9.3 关键纪律重申（防回归）
- **ck 外挂服务与 sl vendored 集成共用同一份 `core/` + `__init__.py` 导出**（server.py:18 注释明示）。因此：删 `Tier` 导出（§6.1）必须同步验证 `serve/` 导入链（E4），否则外挂服务启动即 `ImportError`。
- **G1 改动对两类消费者一致**：sl vendored 集成（`build_messages` 内部调 ck）与 ck 独立外挂（`server.py` 调 `run_openai`）都经 `run_openai` 同一入口吸收 `body["model"]`——**单一改动点，两类消费者同等受益**，无需为外挂单独写分支。
- **ck 外挂的 model 路由仍归「调用方」**：与 pk 外挂（§8.4 D3）同构——ck 外挂不持有 model→service 路由表，只透明转发 `body["model"]` 给注入的 `LlmProvider`；真正的 service 路由在 sl 侧 `sl_llm_provider`（D1 推荐 A）或未来 ck 外挂的 `LlmProvider` 注入方。

### 9.4 对「ck 独立性」的总判断
- **去 tier**：零影响 ck 外挂（tier 从未进 `serve/`），仅 §6.1 删数据结构 + E4 回归测试。
- **G1 透传**：增强 ck 外挂多模型能力，仅需 E1/E2 契约补全（逻辑零改），且 sl 集成与外挂共用 `run_openai` 入口——**改动同源、收益同享、无分叉风险**。
- **G3 tool_calls 透传**：**对 ck 外挂有正向且必需的影响**——`serve/` 的 envelope 当前只塞 `content`/`ext`，独立外挂因此也吃不到工具调用；G3 修复须同步 E5（envelope 两处 + schema 补 `tool_calls`），使 ck 独立外挂也能驱动工具循环。属「加法字段，默认 None 时省略键」，**零破坏旧调用方**。
- **结论**：前述 §六/§七 的细化**已保障 ck 外挂独立性**，但缺「E1–E4 同等修正」的显式清单；本 §九 补齐（含 E5），使 dev-plan 承接时不会遗漏外挂侧验证。

---

## 附：更新日志

- 2026-08-23 v0（概念首稿，未发布·无版号）：基于 `integration_sl_draft` v3.7 §11.1 重述 ck 侧需改/不改/守约项，锁定 ck 责任边界；标注 ck 设计文档 `tier` 回写提示。
- 2026-08-23 v1（升级为 dev-plan 前置文档）：细化 §六为 ck 待实施改造清单（去 tier 代码落点 / G1 / G2 / G4 / region）；重写 §七为最终决策依据表（D1–D5，含选项/事实/影响/风险/推荐）；新增 §八 pk 去 tier 探查细化与愈合映射（D2/D3 判断依据）；明确本件为研发计划前置概念件。
- 2026-08-23 v2（补 ck 外挂独立性评估）：新增 §九 ck 外挂服务独立性与同等修正——盘点 `serve/`（server.py + session_store.py）零 tier 残留、G1 对独立外挂为正向增强需 E1–E4 契约补全；明确去 tier 零冲击外挂、G1 改动经 `run_openai` 同源入口两类消费者同享；D1 决策表补「对 ck 外挂服务的影响」维度。
- 2026-08-23 v3（用户拍板 D1–D5 落地）：D1 已决=扩 `service_name=None` 且不传按默认回落；D2 重新定性=planning/normal/summary 为 sl 分形家族**新增三种类型（增强/扩充，非分裂）**，内核不再自持阶段标识、改由 sl 按家族类型决策传入；D3 已决=路由表归 pk 外挂（家族收纳）；D4 已决=先 ck 后 pk；D5 已决=gate_set 恒非流。全文「愈合分叉」措辞改为「家族类型扩充/收纳」，§八标题与 8.2/8.3/8.4 同步修订，§七已决项汇总收口 D1–D5。
- 2026-08-23 v4（用户拍板 G3 必须修·纠正概念错误）：原 v3 把 G3 列为「ck 不改、sl 绕开 ck 调工具」系自相矛盾（与「分形全部走 ck、ck 是主路径基座」冲突）——**翻转 G3 为「必须修」**：ck 返回层（`_assemble_and_gate` 两处）原样透传 `tool_calls`，sl 在 ck 完整响应上做工具循环；§2.5 重写、§四收敛关系修正（sl 不经 ck 直连 LLM 的误区更正）、§6.6 新增 G3 代码落点表、§七已决项汇总移除「G3 不改」并翻转为必须修、§九新增 E5（serve envelope + CK_SCHEMA 透传 tool_calls 的等同修正）、9.4 总判断补 G3 对独立外挂的正向必需影响。
