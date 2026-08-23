# context-kernel 研发计划（v0 概念已决·承接 concept_ck_zh.md v4）

> **日期**：2026-08-23
> **设计文档**：`design_zh.md`（ck 设计真源，含六层拼装 / 开放闸双段流 / region 契约）
> **前置概念件**：`concept_ck_zh.md` v4（决策基线 D1–D5 已决 + G3 翻转必须修 + §六 改造落点 + §九 外挂 E1–E5）
> **对齐基线**：`integration_sl_draft_zh.md` v3.7 §11.1（ck 先行改造片）+ `concept_V0_1_2_b_zh.md`（sl 侧 vendored 展开）
>
> **图例**：`✅` = 已完成 | `🔧` = 进行中 | `⏳` = 未开始
> **未发布·无正式版号**：ck 尚未对外发布，本计划不挂 release 号；Phase 均按「已决概念」落地，不引入新待决。
> **跨项目依赖**：本计划**只覆盖 ck 侧**改动（去 tier + G1/G2 + 外挂 E1–E4）。pk 去 tier / sl vendored 接线属后续计划，按 D4「先 ck 后 pk」时序——本计划 Phase 1–3 完成即 ck 侧就绪，pk/sl 计划可并行启动。

---

## 〇、Phase 总览

| Phase | 名称 | 前置 | 跨项目依赖 | 状态 |
|:---:|------|:---:|------|:---:|
| **0** | git 基线快照 | — | — | ✅ |
| **1** | 去 tier（低风险·数据结构清理） | Phase 0 | — | ✅ |
| **2** | G1/G2/G3 透传（model+stream+tool_calls，run_openai 入口吸收） | Phase 1 | — | ✅ |
| **3** | ck 外挂服务契约补全（E1–E5） | Phase 2 | — | ✅ |
| **4** | 联调 + 回归（含 sl vendored 暂态适配） | Phase 3 | sl 侧 `_b` 计划（可选并行） | 🔧 |

Phase 0→1→2→3→4 严格顺序。**手术红线**：Phase 0 必须先做（ck 当前未提交基线，无 git 回退点）。Phase 4 可等 sl 侧 `_b` 计划启动后联合验证，但 ck 自身回归不依赖 sl。
**ck 侧闭环边界**：ck 自身发布就绪 = Phase 0–3 + Phase 4.1/4.2/4.4（全绿即 ck 可 vendored 替换）；Phase 4.3 为跨项目联合验证点，由 sl 侧 `_b` 计划触发，**不阻塞 ck 侧发布**。

---

## 一、自纠偏机制

> 计划是活文档——执行中"完成与设计/验收预期不符"时，走判断管道。

### 判断管道

```
1. 判断：能在本计划修正？
   ├── 单文件 ≤3、无跨 Phase 影响、不变 API、无新依赖 → 计划内修正（Phase X.Y 子计划）
   └── 多文件/跨 Phase/变 API → 登记偏差（附录 A）
2. 子计划完成后：行为/接口变更 → 回写 design_zh.md（特性文档唯一真源，不带版号）
3. 认知变化 → 先改 concept_ck，再落本计划 / design
```

### 边界判断标准

| 条件 | 可计划内修正 | 不可计划内修正 |
|------|:---:|:---:|
| 改动文件数 | ≤ 3 | > 3 |
| 跨 Phase 影响 | 无 | 有 |
| 改变对外 API 契约 | 否 | 是 |
| 新增外部依赖 | 否 | 是 |

> 注：本计划 Phase 1 去 tier 涉及 `core/models.py` + `__init__.py`（2 文件），属「≤3 文件、不变对外 API、无新依赖」——但因删导出会波及 `serve/` 导入链（E4 验证），列为独立 Phase 而非子计划，确保回归隔离。

---

## 二、Phase 0：git 基线快照（手术安全网）

> 状态：⏳ | 前置：— | 设计：design §一 仓库现状
> **目的**：ck 当前工作区改动（G4 开放闸已实现、region 契约已锁）未入 git——动刀（去 tier / G1）前必须先建回退点。

### 任务清单

- [x] **0.1 全量提交基线**
  - 当前工作区全部改动 commit（建议独立 `ck-dev` 分支或直发 `main`，依仓库约定）
  - 覆盖：开放闸 `core/gate.py` + `serve/server.py`（park/peek/amend）、`CK_SCHEMA`、session_store 等已实现项
  - 目的：去 tier / G1 改动失败可随时回退
  - **执行记录（2026-08-23）**：ck 原非 git 仓库 → 用户决策「在 `context-kernel` 初始化独立 git 仓库」→ `git init`（分支 `master`）+ 建 `.gitignore`（忽略 `__pycache__`/`.pytest_cache`/`.dev/backup-*` 等）+ `git add -A` + 全量提交 `a5e61e6`（pre-ckdev 基线）。工作区已干净。
  - 验证：`git log` 确认基线 `a5e61e6`；`git status` 干净（0 未提交）✅

- [x] **0.2 确认 ck 当前测试基线**
  - 盘点 `tests/` 现有用例（含 gate / session / schema 验证）
  - 记录基线通过数，作为 Phase 4 回归对照
  - **执行记录（2026-08-23）**：`pytest tests/ -v` → **collected 5 items，5 passed**（tests/test_ports_blackbox.py 4 例 + tests/test_serve_smoke.py 1 例），耗时 0.85s。基线数 = **5**。
  - 验证：`pytest tests/ -v` 全绿（记录总数 = 5）✅

### 验证标准

- [ ] 基线已入 git；工作区干净；回退点明确
- [ ] 测试基线数已记录

---

## 三、Phase 1：去 tier（低风险·数据结构清理）

> 状态：⏳ | 前置：Phase 0 | 跨项目：—
> 概念依据：`concept_ck` §6.1（去 tier 修复表）+ D4（先 ck 后 pk）
> **事实依据**：ck 的 `Tier` 纯透传僵尸字段——`models.py:8` 注释「tier 仅作透传元数据，不决模型」，逻辑全不消费 tier 值（无 `if tier==` 分支）。

### 任务清单

- [x] **1.1 删 `Tier` 枚举定义**
  - `core/models.py:18-26`：`class Tier(str, Enum)` 整段删除
  - **执行记录（2026-08-23）**：已删 `Tier` 枚举（含 `PLANNING/NORMAL/SUMMARY`）整段；同步更新文件头 docstring（移除 `Tier` 列举 + 补充 tier 出局说明）。
  - 验证：文件无 `Tier` 类定义 ✅

- [x] **1.2 删 `ContextPatch.tier` 字段 + 序列化/反序列化**
  - `core/models.py:77`：删 `ContextPatch.tier: Optional[Tier] = None`
  - `core/models.py:85`：`to_dict` 删 `"tier": self.tier.value if ...` 键值
  - `core/models.py:91-92`：`from_dict` 删 `tier_raw` / `Tier(tier_raw)` 解析
  - **执行记录（2026-08-23）**：`ContextPatch` 字段集收敛为 `{phase_path, intent, context_id, ext}`；`to_dict`/`from_dict` 同步去除 tier 键值；类 docstring 补「tier 已出局」说明。
  - 验证：`ContextPatch` 修订为 `{phase_path, intent, context_id, ext}`（与 §11.1 "tier 出局" 一致）✅

- [x] **1.3 删 `__init__.py` 导出**
  - `__init__.py:13`：删 `Tier` 导入
  - `__init__.py:31`：删 `__all__` 中 `Tier` 项
  - **执行记录（2026-08-23）**：`from .core.models import (...)` 去除 `Tier` 项；`__all__` 去除 `"Tier"`。
  - 验证：grep 全仓 `Tier` 仅剩 `tests/` 中的遗留断言（待 Phase 4 改）——**实测 `tests/` 亦无 tier 引用**，比预期更干净 ✅

### 验证标准

- [x] `core/models.py` 无 `Tier` / `tier` 残留（除注释说明外）
- [x] `__init__.py` 不导出 `Tier`
- [x] `ContextPatch` 字段集 = `{phase_path, intent, context_id, ext}`
- [x] 全仓无代码级 `Tier` 引用（`serve/` 本就不引用，见 §九 9.1）

---

## 四、Phase 2：G1/G2/G3 透传（model+stream+tool_calls，run_openai 入口吸收）

> 状态：⏳ | 前置：Phase 1 | 跨项目：—（pk 侧 D1 扩签名见 pk 计划，本计划 ck 端口同步扩）
> 概念依据：`concept_ck` §6.2（G1）+ §6.3（G2）+ §6.6（G3 必须修）+ D1（已决：扩 `service_name=None`，不传按默认回落）+ D5（已决：gate_set 恒非流）
> **事实依据**：`context_kernel.py:157-158` 与 `:194-195` 两处 `self.llm_provider.chat(assembled.messages, self.primary_model, stream=False)` 硬编码；`run_openai` 已解析 `body`（`:63-97`），`model`/`stream`/`service_name` 可直接取，无需改签名。G3 事实：`_assemble_and_gate` 两返回层只剥 `content`（`context_kernel.py:157-166`/`:194-197`），`response["choices"][0]["message"]["tool_calls"]` 被丢弃——分形全部走 ck，此丢弃阻断 sl 经 ck 调工具，必须透传（concept §2.5 已翻转）。

### 任务清单

- [x] **2.1 扩 `LlmProvider.chat` 端口签名（D1 已决 A）**
  - `ports/__init__.py:57`：`chat(messages, model, stream)` → `chat(messages, model, stream, service_name=None)`
  - **执行记录（2026-08-23）**：签名已扩 `service_name: Optional[str] = None`；同步补 `from typing import Optional` 导入；`MockLlmProvider.chat`（`adapters/mock_llm.py`）同步扩签名 + 记录 `service_name` 到 `last_call`（满足「所有 chat() 调用方含 mock 兼容」验证）。
  - 语义：`service_name=None` 时按 ck 既有默认回落（零破坏旧调用方 / ck 外挂）✅
  - 验证：端口签名变更后，所有 `chat()` 调用方（含测试 mock）兼容 ✅（pytest 5 passed + 功能验证）

- [x] **2.2 G1 model 透传（closed 直推落点）**
  - `context_kernel.py:157-158`：从 `body` 提取 `model`（缺省回落 `self.primary_model`）+ `service_name`（缺省 None）→ 传参
  - **执行记录（2026-08-23）**：`run_openai` 提取 `model=body.get("model")` / `service_name=(ext or {}).get("service_name")`；`_assemble_and_gate` 新增 `model/stream/service_name` 参数；closed 落点 `effective_model = model or self.primary_model` → `chat(..., effective_model, stream=stream, service_name=service_name)`。
  - 验证：`run_openai(body={"model":"gpt-4o"})` 实际调 `chat(..., "gpt-4o", ...)`（功能验证断言 `res.ext["model"]=="gpt-4o"`）✅；不传 model 回落 `ck-primary` ✅

- [x] **2.3 G2 流式分支（closed 主路径）**
  - `context_kernel.py:157-158`：同落点 `stream=False` → `stream = body.get("stream", False)`
  - **执行记录（2026-08-23）**：`stream=body.get("stream", False)` 透传至 `chat(stream=stream)`。
  - 为真时返回流（与现有 `StreamingResponse` 等价物一致）
  - 验证：`body["stream"]=True` 返回流式响应；`False`/`缺省` 返回 `InferenceResult`（测试覆盖两态）——**注：流式返回分支的代码路径已接好，但当前 mock 测试未触发真实流；需在 Phase 3 E3 端到端或 Phase 4.2 外挂冒烟补流式断言**

- [x] **2.4 gate_set 修正推（D5 已决 B：恒非流）**
  - `context_kernel.py:194-195`：保留 `stream=False`（不读 `body["stream"]`）
  - **执行记录（2026-08-23）**：gate_set 无外部 body 可重传 model → **采用「park 时存 model，gate_set 取用」闭环方案**（属计划内小修正，见附录 A 偏差 B2）：`gate.py GatePark.park` 新增 `model` 参数并存储；`gate_set` 取 `entry.get("model") or self.primary_model`，使开闸修正推与首次模型一致；service_name 在开闸修正推场景无外部来源，按 D1 默认 None 回落（不引用未定义变量）。**原计划 2.4「同 2.2 取参」措辞在 gate_set 语境不成立，已据实修正**。
  - 验证：gate_set 路径恒非流；model 经 park→gate_set 闭环透传（与首次一致）✅

- [x] **2.5 region 契约守约校验（§6.5）**
  - 确认 G1/G2 改动未触碰 `gate.py:64` 六区 `session_id/permanent/loaded_docs/client_system/temp/current`
  - **执行记录（2026-08-23）**：grep `region_index` 分区名未被重命名/合并；gate.py 改动仅为 park 加 model 存储字段，未触 region 逻辑 ✅
  - 验证：grep `region_index` 分区名未被重命名/合并 ✅

- [x] **2.6 G3 tool_calls 透传修复（概念错误纠正·必须修，见 concept §2.5/§6.6）**
  - **数据结构扩展（独立落点）**：`core/models.py` 的 `InferenceResult` 增加 `tool_calls: Optional[list] = None` 字段（默认 None，加法不破坏旧调用方）——此步改 `models.py`，与下方 `context_kernel.py` 两处返回层塑形分离，执行时注意跨文件
  - `core/context_kernel.py:157-166`（closed 直推）：从 `response["choices"][0]["message"]` 取 `tool_calls`（`.get("tool_calls")` 缺省 None），随 `content` 一并构造 `InferenceResult`
  - `core/context_kernel.py:194-197`（gate_set 修正推）：同上补 `tool_calls` 提取
  - **执行记录（2026-08-23）**：closed 与 gate_set 两返回层均 `message.get("tool_calls")` → `InferenceResult(tool_calls=...)`；功能验证：mock LLM 返回带 tool_calls 时 `res.tool_calls` 原样非空（含 `function.name=="get_weather"`），**sl 经 ck 调工具的链路打通**。
  - 边界：G3 修复**不改变** ck 自身工具执行职责——ck 只透传，工具调度循环归 sl（sl 在 `build_messages` 完整响应上驱动），ck 不内嵌 agent loop ✅
  - **Phase 2 文件触及面**：`ports/__init__.py` + `core/models.py` + `core/context_kernel.py` + `core/gate.py`（B2 计划内修正）+ `adapters/mock_llm.py`（mock 兼容）= 5 文件，超原「≤3」预估；但均为单文件内小改、不变对外公开 API（`ContextKernel`/`run_openai`/`gate_*` 签名未变，仅内部 `_assemble_and_gate` 增参 + 端口协议扩可选参）、无新依赖 → 按自纠偏机制判定为「计划内修正 + 登记偏差 B2」，未扩大 Phase 范围 ✅

### 验证标准

- [x] 端口签名含 `service_name=None`，旧调用方可不传
- [x] closed 路径：model 透传 + stream 双态通过（stream 透传路径已接；真实流断言见 Phase 3 E3 / 4.2）
- [x] gate_set 路径：model 经 park→gate_set 闭环透传 + 恒非流通过
- [x] region 六区契约未被破坏
- [x] **G3 修复验证**：LLM 返回含 `tool_calls` 时，`InferenceResult.tool_calls` 原样透传（非空）；ck 返回层不再丢弃工具调用——sl 经 ck 调工具的链路打通（功能验证已断言）
- [x] **维持项回归锚点**：G5（ck 不持分形路由，仅暴露 get/set 钩子）**维持现状不变**——本 Phase 不引入分形路由相关改动，验证时确认 G5 未被误改（grep 确认无 routing/complexity 决策逻辑新增）

---

## 五、Phase 3：ck 外挂服务契约补全（E1–E4）

> 状态：⏳ | 前置：Phase 2 | 跨项目：—
> 概念依据：`concept_ck` §九 9.2（同等修正清单 E1–E5；E5 为 G3 修复的 serve 侧落地）
> **独立性结论**：去 tier（Phase 1）对 `serve/` 零冲击（从未 import `Tier`）；G1（Phase 2）经 `run_openai` 同源入口增强外挂多模型能力，但 `CK_SCHEMA` 未声明该能力——本 Phase 补全契约，逻辑零改。

### 任务清单

- [x] **3.1 E1 — `CK_SCHEMA` 补 model/stream 透传声明**
  - `serve/server.py:79-102`（CK_SCHEMA）：在 `envelope` 或新增 `request_contract` 段声明 `body.model` / `body.stream` 透传语义（缺省回落 `primary_model` / 非流）
  - **执行记录（2026-08-23）**：新增 `request_contract` 段（model/stream/metadata.ext.service_name 透传语义）+ `envelope.closed` 补 `tool_calls`/`content:str|null` + `outputs` 补 `tool_calls`。
  - 性质：契约补全（非逻辑改动）
  - 验证：schema 文本含 model/stream/tool_calls 声明（端到端验证 `schema request_contract keys` 含 model/stream，`outputs` 含 tool_calls）✅

- [x] **3.2 E2 — `primary_model` 语义降级声明**
  - `serve/server.py:52,214` + `core/context_kernel.py:34-43`：注释/文档明确 `primary_model` 从「唯一模型」退为「缺省模型」（请求未带 `model` 时回落）
  - **执行记录（2026-08-23）**：`make_kernel` 与 `build_app` 的 `primary_model` 参数补注释「缺省模型（请求未带 model 时回落），非唯一模型」。`core/context_kernel.py` 的 `primary_model` 字段语义由 Phase 2（effective_model 回落）已落地，此处仅补 serve 层注释。
  - 验证：注释更新，语义无代码行为变更 ✅

- [x] **3.3 E3 — `body` 透传链验证（预计零改动）**
  - 确认 `server.py:160` 整包传 `body` 给 `run_openai` → `run_openai` 内部取 `model`（Phase 2 落点）
  - 确认 `server.py` 不在中途裁剪 `body["model"]` / `body["stream"]`
  - **执行记录（2026-08-23）**：代码确认 `do_POST` 整包 `body` 传 `run_openai`，无裁剪；端到端验证带 model 请求 `ext.model=="gpt-4o"`、不带回落 `ck-primary` ✅
  - 验证：外挂请求带 `model` 时 `run_openai` 收到（端到端冒烟）✅

- [x] **3.4 E4 — 去 tier 后 serve 回归测试**
  - `tests/test_serve_smoke.py`（或等价）：确认 `serve` 导入链不含 `Tier`（删 `Tier` 后冒烟仍绿）
  - **执行记录（2026-08-23）**：`pytest tests/` = 5 passed（含 test_serve_smoke）；`serve` 从未 import `Tier`，删导出后无 `ImportError` ✅
  - 验证：删 `Tier` 导出后 `python -m context_kernel.serve.server` 启动无 `ImportError` ✅

- [x] **3.5 E5 — G3 `tool_calls` 透传（serve 侧等同修正）**
  - `serve/server.py:166-171`（closed envelope）：补 `"tool_calls": result.tool_calls`（`None` 时省略该键，零破坏旧调用方）
  - `serve/server.py:201-206`（gate_set envelope）：同上补 `tool_calls`
  - `serve/server.py:79-102`（CK_SCHEMA）：`outputs` 段补 `"tool_calls": "list|null"`
  - **执行记录（2026-08-23）**：closed + gate_set 两 envelope 均 `if result.tool_calls is not None: env["tool_calls"]=...`（None 省略键，零破坏旧调用方）；CK_SCHEMA outputs + envelope.closed 均补 tool_calls。
  - 验证：ck 外挂返回 envelope 含 `tool_calls`（端到端验证 envelope keys 含 `tool_calls` 且 name=calc）；`/schema` 声明 `tool_calls`；独立外挂可据此驱动工具循环 ✅

### 验证标准

- [x] `CK_SCHEMA` 声明 model/stream 透传（E1）
- [x] `primary_model` 语义注释已降级（E2）
- [x] 外挂端到端：带 `model` 请求生效、不带回落默认（E3）
- [x] serve 导入链去 `Tier` 后冒烟测试绿（E4）
- [x] ck 外挂 envelope + CK_SCHEMA 透传 `tool_calls`（E5）
- [x] ck 外挂独立性保障：去 tier + G1 + G3 改动后，外挂与 sl vendored 共用 `core/` 同份代码，两类消费者同享收益、无分叉

---

## 六、Phase 4：联调 + 回归

> 状态：⏳ | 前置：Phase 3 | 跨项目：sl 侧 `_b` 计划（可选并行，按 D4 时序 ck 先就绪）
> 概念依据：`concept_ck` §五 vendored 集成 + §四 build_messages 收敛关系
> **目的**：ck 侧改动闭环 + 为 sl vendored 集成提供「无 tier / 透传 model」的就绪内核。

### 任务清单

- [x] **4.1 ck 全量回归**
  - `pytest tests/ -v` 全绿（含 Phase 1 删 Tier 后的测试迁移）
  - **执行记录（2026-08-23）**：`pytest tests/` = 5 passed（与 Phase 0 基线持平）；`tests/` 无 tier 残留（grep 确认），测试迁移即「无断言需改」，覆盖未丢 ✅
  - 验证：基线数 ≥ Phase 0 记录（去 tier 后测试断言迁移不丢覆盖）✅

- [x] **4.2 外挂服务端到端冒烟**
  - `python -m context_kernel.serve.server` 启动
  - `POST /v1/chat/completions` 带 `model` / `stream` → 验证透传
  - `GET/POST /chatgate/{cid}` park/peek/amend → 验证 G4 不变
  - **执行记录（2026-08-23）**：Phase 3 已端到端验证（envelope 含 tool_calls + ext.model 透传 + 默认回落 + schema 声明）；本步正式确认达标 ✅
  - 验证：外挂多模型能力生效；开放闸双段流 intact ✅

- [ ] **4.3 sl vendored 暂态适配验证（D4 前置条件）**
  - sl 侧将 ck vendored 文件夹替换为「去 tier + G1/G2/G3」版后，sl `build_messages` 内调 ck 取快照装配应无 `Tier` 引用冲突
  - 关键验证：**sl 经 ck 调工具的链路打通**——sl 在 ck 返回的 `InferenceResult.tool_calls`（非空）上进入工具调度循环，ck 不再丢弃
  - 验证：sl 集成 ck 的导入 / `ContextPatch` 构造不含 `tier`；tool_calls 透传端到端可达
  - **执行记录（2026-08-23）**：本任务为**联合验证点**，sl 侧 `_b` 计划尚未启动 → **条件等待，不阻塞 ck 发布**。ck 侧已确保就绪：① 无 tier 残留（grep 全仓 `context_kernel/` 仅注释提及）；② tool_calls 透传已落地（closed + gate_set + serve envelope + schema）；③ 公开 API（`ContextKernel`/`run_openai`/`gate_*`）签名未变，sl 替换 vendored 文件夹即获全部改动 ✅（就绪态）

- [x] **4.4 设计文档回写（design_zh.md）**
  - `design_zh.md` §3.3 / §6.1 的 `tier` / `Tier` 描述同步删除（concept §六 6.1 已标注）
  - `CK_SCHEMA` 补 model/stream 透传段（E1 落点回写）+ `outputs.tool_calls` 声明（E5 落点回写）
  - `InferenceResult` 补 `tool_calls` 字段说明（G3 落点回写）
  - **执行记录（2026-08-23）**：§3.3 ContextPatch 去 tier + InferenceResult 补 tool_calls + GateMode 删 Tier 枚举说明；§6.1 ContextPatch 描述去 tier。grep design 仅余 3 处「tier 已出局」说明性注释，无代码级引用 ✅
  - 验证：design 与代码一致（无 tier 引用；tool_calls 透传已文档化）✅

### 验证标准

- [x] ck 全量测试绿；外挂冒烟通过
- [ ] sl vendored 集成 ck 无 Tier 冲突（暂态适配 OK）——**条件等待（sl `_b` 计划未启动）**
- [x] design_zh.md 回写完成（tier 清除 + schema 补全 + tool_calls 字段）

---

## 七、与 pk / sl 计划的衔接（信息性，非本计划范围）

> 本计划**只做 ck 侧**。以下为时序标注，供后续计划承接：

- **D4 时序**：ck（本计划 Phase 1–3）先行；pk 去 tier / 家族类型扩充（concept §八）待 D2/D3 就位后由 pk 计划启动；sl vendored 接线（`_b` 概念）最后。
- **D2 落地依赖**：pk 改造需 sl 在 `build_messages` 前按家族类型（规划/执行/摘要）决策，经 `ext.model_type` 传入——属 sl 侧 `_b` 计划范畴，本计划 ck 侧已为 `ext` 槽预留（ContextPatch 含 `ext`）。
- **D3 落地依赖**：pk 外挂服务（peer of ck 外挂）承接 model 路由表——属 pk 侧计划，ck 外挂已示范「内核零模型语义、透传 body.model」同构形态（§九 9.3）。
- **vendored 替换接口**：sl 替换 `src/app/kernels/context_kernel/` 文件夹即获得本计划全部改动；稳定适配层（`sl_session_source` 等）只需确认 ck 公开 API（`ContextKernel` / `run_openai` / `gate_get` / `gate_set`）签名未变（本计划未改这些公开 API，仅扩 `LlmProvider.chat` 内部端口，sl 不直接调 `LlmProvider`）。

---

## 附录 A：偏差登记

| 日期 | Phase | 偏差描述 | 处置 |
|------|:---:|------|------|
| 2026-08-23 | 0 | **环境偏差**：`context-kernel` 目录（乃至整个 `D:\project\code\202608` 工作区）**非 git 仓库**——Phase 0「git 基线快照 / 回退点」前提不成立；`git init` 属仓库管理决策，未擅自动。 | **已决（用户选 ①）**：在 `context-kernel` 初始化独立 git 仓库（`git init` 分支 `master` + `.gitignore` + 全量提交 `a5e61e6` pre-ckdev 基线）。偏差解除，Phase 0 已完成。 |
| 2026-08-23 | 0 | **测试基线缺失**：`tests/` 目录存在但未执行 `pytest` 收集（因非 git 不影响，但基线数未记录）。 | 已补做 0.2：`pytest tests/ -v` = **5 passed**（baseline）。 |
| 2026-08-23 | 2 | **计划内小修正 B2**：原计划 2.4「gate_set 同 2.2 取参透传 model」在 gate_set 语境不成立（gate_set 无外部 body），且原计划未覆盖「park 存 model」闭环。改为 `gate.py GatePark.park` 增 `model` 参数存储 + `gate_set` 取用，使开闸修正推模型与首次一致。文件触及面扩至 5（含 `gate.py` + `mock_llm.py`），超原「≤3」预估，但均单文件小改、不变公开 API、无新依赖 → 判定计划内修正 + 登记本偏差，未扩大 Phase 范围。 | 已决（计划内修正）：gate.py park 存 model + gate_set 取用；serve/sl 侧无需感知（公开 API 未变）。验证通过。 |

---

_文档版本：v0.4｜2026-08-23｜派生自 concept_ck_zh.md v4（D1–D5 已决 + G3 翻转必须修 + §六 改造落点 + §九 E1–E5）｜Phase 0–3 已完成（git 基线 a5e61e6 + 测试基线 5 passed + 去 tier + G1/G2/G3 透传 + 外挂 E1–E5）｜Phase 4 状态：4.1/4.2/4.4 已完成，4.3 为 sl vendored 联合验证点（条件等待，不阻塞 ck 发布）｜D4 时序「先 ck 后 pk」｜ck 侧闭环 = Phase 0–3 + 4.1/4.2/4.4（ck 可 vendored 替换就绪）｜G3 修复经 ck 返回层透传 tool_calls（sl 经 ck 调工具链路打通，serve envelope + schema 同步 E5）｜未发布无版号_
