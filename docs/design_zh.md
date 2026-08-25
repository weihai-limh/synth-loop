# synth-loop 设计文档

> **文档类型**：技术设计
> **版本**：v0.1.2_e | **日期**：2026-08-26
> **适用范围**：synth-loop
> **关联文档**：`product_zh.md`、`api_zh.md`
>
> 本文档回答「工程上怎么做」。所有设计以代码真相为依据。

---

## 一、核心定位

synth-loop 是一个 **以 LLM 网关形态暴露的任务处理中枢**——对外是一张 LLM 网关的"脸"（OpenAI/Anthropic 兼容端点），对内是一个做任务分派与收束的交换中枢：对每次请求做整套决策（走哪条路径、用什么模型、装什么上下文、过什么闸、用哪个模型、怎么多步推理），最终把所有这些推理收束到唯一推理落点（`sl_llm_provider`）。

```
API 代理：请求 → 转发 → 响应（不改语义）
synth-loop：请求  → 分形路由（选一条路径）→ 上下文内核（ck 拼装 + 闸）→ 任务链推理 → 唯一推理落点 → 流式返回
```

### 是什么 / 不是什么

| 是 | 不是 |
|------|------|
| 任务处理中枢——分派 + 收束（`src/sl-py/app/services/sl_llm_provider.py` 唯一推理落点） | 匹配引擎（策略匹配由外部策略服务负责） |
| 协议兼容端点——OpenAI + Anthropic 双协议接入（`src/sl-py/app/services/protocol_translator.py`） | API 代理/中立网关——不做请求透传，每个请求都经历编排决策 |
| 上下文内核承接方——ck 六层拼装 + 闸监听（`src/sl-py/app/kernels/context_kernel/`） | LLM 框架（不封装 LLM 调用） |
| 任务处理者——分形路由、相位推理（pk）、统一闸管理、统一数据面 | 策略持有者（策略由外部策略服务管理） |

---

## 二、系统架构

### 2.1 部署拓扑

```
┌──────────────┐     OpenAI/Anthropic      ┌──────────────────┐
│  任何 Agent  │ ──────────────────────→   │   synth-loop     │
│  (客户端)    │                           │   localhost:13155 │
└──────────────┘                           └────────┬─────────┘
                                                    │
                          ┌─────────────────────────┼─────────────────────┐
                          ▼                         ▼                     ▼
              ┌────────────────────┐    ┌────────────────────┐  ┌──────────────────┐
              │   strata-match     │    │   下游 LLM API     │  │    text-cli       │
              │   localhost:13156  │    │  OpenAI/Anthropic  │  │  指令执行引擎     │
              │   策略 + Prompt    │    │                    │  │                   │
              └────────────────────┘    └────────────────────┘  └──────────────────┘
```

**设计依据**（`src/sl-py/app/config.py` `PROJECT_ROOT` / `DEPLOY_DIR` / `SRC_DIR` 路径常量）：三组件通过 HTTP 解耦，每层可独立演进、独立替换。synth-loop 消费 strata-match 输出，不依赖其内部实现；可降级运行。

### 2.2 平面/分层

| 平面 | 组件 | 职责 | 代码位置 |
|------|------|------|---------|
| **用户面** | 外部客户端 | 通过 OpenAI/Anthropic 协议发起请求 | 外部 或壳`src/sl-web-chat/` |
| **编排面** | synth-loop | 分形决策、策略注入、任务链推进、SSE 流式 | `src/sl-py/` |
| **策略面** | strata-match | Prompt 匹配、skills 技能分片、工具定义、Assets | 外部服务 |
| **执行面** | text-cli | 分布式指令执行、能力发现 | 外部服务 |
| **调度管理面** | 管理面板 + 事件总线 | 会话监控、任务链追踪、Job 管理 | `src/sl-py/public/` + `src/sl-py/app/routers/admin.py` |

### 2.3 外部依赖接口

| 外部服务 | 端点 | 鉴权 | 调用范式 | 代码引用 |
|---------|------|------|---------|---------|
| strata-match | `POST /api/v1/query` | 无（内网） | HTTP JSON request/response | `src/sl-py/app/services/strata_match_client.py` |
| strata-match | `POST /api/v1/users` | 无 | HTTP JSON（联动注册） | `src/sl-py/app/routers/admin.py` |
| strata-match | `POST /api/v1/jobs` | 无 | HTTP JSON（open/close） | `src/sl-py/app/services/job_store.py` |
| 下游 LLM | `POST /v1/chat/completions` | API Key | OpenAI 兼容 HTTP | `src/sl-py/app/services/downstream_llm.py` |
| text-cli | `POST /text-cli/cli`（经运行时表路由） | 内网 | HTTP JSON | `src/sl-py/app/services/textcli_enhanced_client.py` |


---

## 三、主线服务设计

### 3.1 路由层（`src/sl-py/app/routers/`）

| 能力 | 实现 | 说明 |
|------|------|------|
| OpenAI 入口 | `chat.py` — `chat_completions()` + dispatch 决策链 | `/v1/chat/completions` |
| Anthropic 入口 | `anthropic_chat.py` — 请求翻译 + dispatch | `/v1/messages` |
| 数据面包 | `packets.py` — 上下文数据包提交 + 校验 | `/v1/packets`|
| 数据面包-永久区通道 | `longdata.py` — doc/memory 引入/删除/列出 | `/v1/longdata` |
| 健康检查 | `health.py` | `/health` |
| 异步任务 API | `tasks.py` — GET + POST cancel | `/api/v1/tasks/{id}` |
| 运行时表管理 API | `runtime_endpoints.py` — CRUD | `/api/v1/runtime-endpoints`（admin scope） |
| 制品数据面 | `artifacts.py` — 相位产物查询 | `/api/v1/artifacts/{id}`、`?pipeline_id=` |
| 统一闸钩子面 | `gate.py` — gate_manager 配置（_b 新增） | `/gate-manager/config` GET/PATCH |
| 管理面板 | `admin.py` — HTML 页面路由 | `/admin/sessions` 等 |

### 3.2 编排服务层（`src/sl-py/app/services/`）

| 能力 | 实现 | 说明 |
|------|------|------|
| 复杂度分类 | `complexity_classifier.py` | 规则匹配 → chat / task_chain / fractal |
| 执行路由 | `execution_router.py` | 分形决策 + 模型选择 + 下游调用编排 |
| 任务链服务 | `task_chain_service.py` | 单步闭环：写 tasks 表(queued)→委托 text-cli --async →轮询→确认闸(内部 `_dispatch_confirm`)→回写(completed/error)，承接 G3 落库责任 |
| 上下文注入 | `context_injector.py` | XML 标签体系上下文组装 |
| 上下文压缩 | `context_compressor.py` | 上游过滤——按复杂度三态处理 system 消息 |
| 上下文标签管理 | `context_manager.py` | 按标签 load/unload/list/refresh 管理永久区上下文 |
| 流式处理 | `streaming_handler.py` | OpenAI + Anthropic SSE 格式输出 |
| 协议翻译 | `protocol_translator.py` | Anthropic ↔ OpenAI 格式互转 |
| strata-match 客户端 | `strata_match_client.py` | HTTP 客户端 + 缓存 + mock |
| 工具适配器 | `strata_match_tool_adapter.py` | strata-match 工具 → OpenAI 格式 |
| 工具分发器 | `tool_dispatcher.py` | 注册 + 路由工具调用 |
| 动态工具执行 | `dynamic_tool_executor.py` | 运行时工具执行（走强化客户端，无 `command.replace`） |
| 降级管理器 | `degradation_manager.py` | 三层降级逻辑 |
| 模型选择器 | `model_selector.py` | 直接透传 service 给 execution_router（_b：llm_routing 配置唯一真源，无 service_map 白名单截断） |
| 唯一推理落点 | `sl_llm_provider.py` | 所有路径（主/相位/工具）收敛；通用 service 选择 + ck 闸集成 + context_id 生成 |
| 推理缝 | `inference_seam.py` | `SlInferenceSeam`：pk 推理缝，暴露到 build_messages，经 ck 拼装 + 闸监听 |
| 统一闸 | `gate_manager.py` |  跨内核闸编排：GateType 五类 + 组合函数注册表 + 跨内核循环 + ck/pk 端口适配 |
| 内核适配层 | `kernel_adapters.py` | sl 侧 ck 组件（SlContextKernel/适配器）+ pk 装配（build_phase_engine）+ `_PkGateAdapter`（_e 接通真实 `PhaseGateExecutor`：async 桥接 + query 受控相位面自实现） |
| 逻辑抽象器 | `logic_abstractor.py` | 关键词判定 subtype |
| 会话管理器 | `session_manager.py` | Session CRUD + 过期清理 |
| DB 写入器 | `db_writer.py` | 异步事件日志写入 |
| Job 存储 | `job_store.py` | 跨组件 Job 协同 |
| Packet 存储 | `packet_store.py` | 内存缓存 + TTL 自动清理 + type 校验（ 类型准入改配置驱动 `packets.types`，空配置回落内置默认） |
| 预处理器 | `preprocessors.py` | 按 type 分发预处理器提取摘要 |
| 永久区数据面 | `longdata.py` | 通道B（永久区）：doc/memory 引入/删除/列出，落 longdata 表 + 永久区 |
| 相位产物桥接 | `sl_artifact_store.py` | 链路 C：实现 pk `ArtifactStore` 端口，落 sl SQLite|
| 运行时表 | `runtime_endpoints.py` | tc 端点配置面：种子幂等 + CRUD + token 加密/脱敏 + alias 路由/降级 |
| 强化客户端 | `textcli_enhanced_client.py` | tc 执行面：四函数 + SPEC 1.3.2 信封直读 + rank 降级 + 鉴权不降级 |
| 相位编排器 | `phase_chat_orchestrator.py` | 相位 chat 契约：薄壳委托 pk `PhaseReasoningEngine`（build_phase_engine 装配；_e 接 sm：planner=PhasePlanPlanner，从 config.strata_match.url 取地址；`handle(..., lang="zh")` 单语硬编码），sl 自持状态机退役 |
| 相位内核 | `kernels/phase_kernel/` | vendored——pk 组件：分形相位树 + 三闸 + 检查点 + 推理缝（SlInferenceSeam 填）+ sm 缝（SmStrategyBundle 结构化策略；_e copy 到 sl）+ i18n（`i18n/*.json` + `core/i18n.py` 加载器，sl 单语默认 zh；不含 serve/） |
| 上下文内核 | `kernels/context_kernel/` | vendored——ck 组件：六层拼装 + 推理闸 + gate_mode（纯副本，sl 适配层封装） |
| 制品数据面 | `artifact_dataplane.py` | 相位产物落库：artifacts 表 + TTL 24h（pk ArtifactStore 适配；artifact_id 唯一必填、其余可空、phase_index_txt 存 phase_path、content 支持 str/dict） |
| token 服务 | `token_service.py` | 统一 token：issue_token/verify_token/map_user_id |

### 3.3 工具层（`src/sl-py/app/tools/`）

| 能力 | 实现 | 说明 |
|------|------|------|
| 专家 Prompt 选择 | `select_system_prompt.py` | 根据意图选人设 |
| 文档加载 | `load_document.py` | 加载到永久上下文区 |
| 文档卸载 | `unload_document.py` | 从上下文区移除 |
| text-cli 发现 | `discover_textcli.py` | 发现可用指令（v0.1.2_a：走强化客户端 discover） |
| text-cli 调用 | `call_textcli.py` | 执行指令（v0.1.2_a：走强化客户端 call） |
| 上下文标签管理 | `context_manager.py` | 按标签管理永久区上下文 |


---

## 四、数据流设计

### 4.1 请求流（热路径）

```
客户端 → POST /v1/chat/completions
  │
  ├── [可选的] auth 中间件 → x-synthloop-user-id 校验 → 401 或继续
  │    代码: src/sl-py/app/middleware/auth.py
  │
  ├── [可选的] 会话复用 → session_manager.get_or_create()
  │    代码: src/sl-py/app/services/session_manager.py
  │
  ├── 消息前置检查层
  │     ├── Task-(.+)-synthloop 匹配 → 查 tasks 表 → 终点响应
  │     ├── <user-memory>...</user-memory> 匹配 → 提取 → 写入永久区
  │     └── 相位路由：带 synth_pipeline 字段 → 解析 action → pk 相位推理（薄壳委托）
  │    代码: src/sl-py/app/routers/chat.py chat_completions()
  │
  ├── 复杂度分类
  │     ├── 层1: 规则匹配（<1ms, 0 token）
  │     └── 层2: 分形 Prompt（1 次 LLM 调用）
  │    代码: src/sl-py/app/services/complexity_classifier.py
  │
  ├── 相位前置拦截：命中相位 XML 标签 → 直接路由到 pk 相位推理（不走分形）
  │     ├── <tc-phase>目标</tc-phase>           → 结构分形（structural，复杂）
  │     └── <tc-phase-chain>目标</tc-phase-chain> → 链式分形（chain，中等）
  │     （标签显式锁定，标签内文本为相位目标；无标签 → 进入分形路由 ↓）
  │
  ├── 分形路由（选一条路径，相位不在此列）
  │     ├── a/chat → 直答
  │     ├── b/prompt_chat → strata-match 策略查询 → 注入
  │     ├── c/task → strata-match 工具注入 → LLM 工具调用循环
  │     └── e,f/task_chain → 任务链拆解执行
  │    代码: src/sl-py/app/routers/chat.py chat_completions() dispatch 决策链
  │
  ├── 主路径归并：所有分支经 build_messages 收束 → sl_llm_provider（唯一推理落点）
  │     ├── 上下文经 ck 拼装 + 闸监听（gate_mode=auto 时 park 返回 pending，可 peek/amend）
  │     └── 模型经 llm_routing 多场景配置（service 透传，无白名单截断）
  │    代码: src/sl-py/app/services/sl_llm_provider.py + kernels/context_kernel/
  │
  └── SSE 流式响应
       代码: src/sl-py/app/services/streaming_handler.py
```

### 4.1.1 错误与降级路径

| 场景 | 行为 | 代码 |
|------|------|------|
| strata-match 超时（>5s） | 自动降级到默认 Prompt | `degradation_manager.py` |
| strata-match 返回错误 | 自动降级到默认 Prompt | `degradation_manager.py` |
| 工具调用失败 | 注入错误信息，LLM 自行处理 | `tool_dispatcher.py` |
| 工具连续失败 3 次 | 熔断，后续调用自动降级 | `tool_dispatcher.py` CircuitBreaker |
| 下游 LLM 不可用 | 返回 502 错误 | `downstream_llm.py` |

### 4.2 配置流（冷路径）

```
config.yaml ──→ load_config() ──→ get_section() / get_*_settings()
  │                                  │
  │  src/sl-py/app/config.py               ├── get_config() → 全局缓存
  │                                  ├── get_section("strata_match")
  │                                  ├── get_auth_settings()
  │                                  ├── get_session_memory_settings()
  │                                  └── get_async_task_settings()
  │
  ├── complexity_rules.yaml ──→ ComplexityClassifier.load_rules()
  ├── model_config.yaml ────→ ExecutionRouter.load_config()
  └── .env（可选） ────→ _resolve_env_vars()
```

### 4.3 数据面流（端点→校验→预处理→注入）

```
用户消息 → chat_completions()
  ├── 校验: messages 格式 / model 名称 / stream 标志
  ├── 前置: 消息前置检查（Task-ID / user-memory）
  ├── 分类: ComplexityClassifier.classify()
  ├── 增强: strata-match 查询 → primary_prompt + tools + assets
  ├── 注入: ContextInjector → XML 标签上下文组装
  │          <context>
  │            <strategy>...</strategy>
  │            <user-memory>...</user-memory>
  │            <references>...</references>
  │            <session>...</session>
  │          </context>
  └── 推理: downstream_llm.chat() / TaskChainService.run()（v0.1.2_d：旧 TaskChainExecutor 删除，改由 TaskChainService 单步闭环驱动）
```

### 4.4 数据面双通道

> **本质**：数据面的分野是**永久区 vs 临时区**，而非 doc/memory vs packets。按持久性分双通道。

```
┌─────────────────────────────────────────────────┐
│ 数据面 —— 双通道（按持久性分野）                  │
├─────────────────────────────────────────────────┤
│  通道A：临时区通道（packets · 已有）              │
│    入口    ：/v1/packets                         │
│    载荷    ：环境上下文（browser/小程序/IM/IoT）   │
│    类型    ：config 准入（packets.types，_c）     │
│    处理    ：预处理器（代码层，按类型专门提取）      │
│    存储    ：内存 + TTL（瞬态，30min 过期）        │
│    注入    ：摘要注入 system prompt               │
├─────────────────────────────────────────────────┤
│  通道B：永久区通道（/v1/longdata · _c 新增）       │
│    入口    ：/v1/longdata（add/del/list）         │
│    载荷    ：doc（文档）+ memory（记忆片段）        │
│    类型    ：写死代码（doc/memory 两类）           │
│    处理    ：通用文本处理（去空格等基本操作）        │
│    存储    ：longdata 表 + 永久区（长期存在）       │
│    注入    ：经 build_messages 从永久区注入         │
└─────────────────────────────────────────────────┘
```

**链路 C 相位产物桥接**：pk 引擎写产物经 `SlArtifactStore`（实现 pk `ArtifactStore` 端口）落 sl SQLite `artifacts` 表——产物不再只进内存，`/v1/artifacts` 可对外取，pk 跨相位上下文传递（`_fetch_parent_context`）经 `fetch` 回链。

---

## 五、统一终端契约

### 对外 API 端点

| 端点 | 协议 | 方法 | 鉴权 | 代码 |
|------|------|------|------|------|
| `/v1/chat/completions` | OpenAI | POST | 无（可选 Bearer） | `chat.py` |
| `/v1/messages` | Anthropic | POST | 无（可选 x-api-key） | `anthropic_chat.py` |
| `/v1/packets` | JSON | POST | 无 | `packets.py` |
| `/v1/longdata` | JSON | POST/DELETE/GET | 无 | `longdata.py` |
| `/api/v1/runtime-endpoints` | JSON | GET/POST/PATCH/DELETE | admin scope | `runtime_endpoints.py` |
| `/api/v1/artifacts/{id}` | JSON | GET | 无 | `artifacts.py` |
| `/api/v1/artifacts?pipeline_id=` | JSON | GET | 无 | `artifacts.py` |
| `/health` | JSON | GET | 无 | `health.py` |
| `/admin/sessions` | HTML | GET | 无 | `admin.py` |
| `/admin/tasks` | HTML | GET | 无 | `admin.py` |
| `/admin/jobs` | HTML | GET | 无 | `admin.py` |
| `/admin/users` | HTML | GET | 无 | `admin.py` |
| `/api/v1/tasks/{id}` | JSON | GET | 无 | `tasks.py` |
| `/api/v1/tasks/{id}/cancel` | JSON | POST | 无 | `tasks.py` |

### 内部服务间契约

| 调用方 → 被调用方 | 接口 | 协议 | 超时 |
|------------------|------|:----:|:----:|
| synth-loop → strata-match | `POST /api/v1/query` | HTTP | 5s |
| synth-loop → strata-match | `POST /api/v1/users` | HTTP | 5s |
| synth-loop → strata-match | `POST /api/v1/jobs` | HTTP | 5s |
| synth-loop → 下游 LLM | `POST /v1/chat/completions` | HTTP | 配置化 |
| synth-loop → text-cli | `POST /text-cli/cli` | HTTP | 配置化 |


---

---

## 六、配置与持久化设计

### 6.1 配置文件拓扑

```
src/sl-py/
├── config.yaml            ← 主配置（服务、auth、session_memory、async_tasks）
├── model_config.yaml      ← 模型端点池 + LLM 路由
└── complexity_rules.yaml  ← 分形规则（仅覆盖两端极值）

src/sl-py/
└── data/
    └── gateway.db         ← SQLite 持久化（aiosqlite）
```

### 6.2 配置表

| 配置段 | 文件 | 默认值 | 代码消费方 |
|--------|------|--------|-----------|
| `strata_match` | `config.yaml` | url=localhost:13156, mock=false | `strata_match_client.py` |
| `runtime_endpoints` | `config.yaml` | enabled=true, default_alias, seeds（v0.1.2_a，替代旧 `textcli` 段） | `runtime_endpoints.py` |
| `pipelines_api` | `config.yaml` | enabled=false（v0.1.2_a 9 端点开关） | `routers/pipeline.py` |
| `downstream_llm` | `config.yaml` | api_base, api_key, default_model | `downstream_llm.py` |
| `auth` | `config.yaml` | enabled=false, required=false | `middleware/auth.py` |
| `session_memory` | `config.yaml` | enabled=true | `routers/chat.py` |
| `async_tasks` | `config.yaml` | enabled=false, max_per_user=3 | `routers/chat.py` |
| `packets` | `config.yaml` | enabled=true, ttl_seconds=1800, types=13 类准入列表（_c） | `packet_store.py`（v0.1.1；_c 类型准入配置驱动） |
| `endpoints` | `model_config.yaml` | 端点池定义 | `execution_router.py` |
| `llm_routing` | `model_config.yaml` | 路由映射（_b：多场景唯一真源，任意 service 透传无白名单截断） | `execution_router.py` → `model_selector.py` → `sl_llm_provider.py` |
| `llm_gateway` | `model_config.yaml` | enabled=false, gateways（多网关注册表，默认未启用） | `downstream_llm.py` |
| `rules` | `complexity_rules.yaml` | chat/task_chain 规则 | `complexity_classifier.py` |
| `logic_categories` | `config.yaml`（来源于外置 `logic_categories.yaml`，真源为 `complexity_rules.yaml` 的 subtypes） | B3 逻辑分类外置：细分路由命中 → 直查细分路由；枚举校验（key 须为 subtypes 真源子集） | `execution_router.py` / `model_selector.py`（v0.1.2_d） |

### 6.3 持久化

| 表 | 文件 | 用途 | 记录数上限 |
|----|------|------|:---------:|
| `session_snapshots` | `gateway.db` | 会话持久化（permanent_system_prompt, temp_history, snapshot） | 无 |
| `events` | `events.jsonl` | 事件日志 | 无 |
| `users` | `gateway.db` | 用户认证（v0.1.1） | 无 |
| `tasks` | `gateway.db` | 异步任务（v0.1.1）；**v0.1.2_d 重写**：旧 `TaskChainExecutor` 删除，落库责任改由 `TaskChainService.run()` 承接（queued→running→completed/error 状态机，经 `get_shared_db()` 统一连接串行写），确认闸为内部私有 `_dispatch_confirm`（非硬依赖） | 无 |
| `runtime_endpoints` | `gateway.db` | tc 端点配置面（v0.1.2_a）：alias 多物理行 + rank 降级 + token 加密 | 无 |
| `artifacts` | `gateway.db` | 相位产物（v0.1.2_a；_c 放宽）：artifact_id 唯一必填、其余可空、phase_index_txt 存 phase_path、content 支持 str/dict，TTL 24h | 无 |
| `longdata` | `gateway.db` | 永久区通道（v0.1.2_c）：doc/memory 引入（id/session_id/type/content/created_at），无 TTL | 无 |
| `tokens` | `gateway.db` | 统一 token（v0.1.2_a）：sha256 hash + scope 分层 | 无 |

---

## 安全设计

### 威胁假设

| 假设 | 影响 | 当前措施 |
|------|------|---------|
| 恶意客户端伪造 user-id | 中——多租户场景 | `auth.enabled=true, required=true` 时强制校验 |
| 下游 LLM API Key 泄露 | 高——财务损失 | Key 配在 config.yaml 中，建议环境变量注入 |
| tc 令牌外泄 | 高 | 运行时表 token 加密（`SELF_TOKEN_ENC_KEY`）+ 管理 API 脱敏 + admin scope |

**最坏情况推演**：config.yaml 泄露 → 攻击者可调用下游 LLM 产生费用。缓解：生产环境使用 `${ENV_VAR}` 环境变量注入（`_resolve_env_vars()` 内置支持，见 `src/sl-py/app/config.py`）。

### 网络分层 / 终端安全 / 隐私合规

| 维度 | 措施 |
|------|------|
| 网络分层 | `auth.enabled` 配置控制，默认关闭（开箱即用） |
| Session 隔离 | `x-synthloop-session-id` 隔离会话，`x-synthloop-user-id` 隔离用户 |
| token 双轨 | `x-synthloop-token`（user/service/admin scope）验权 → `x-synthloop-user-id` 归身份；运行时表管理 API 要求 admin scope |

---

## 非功能性设计

### 可观测性

| 能力 | 实现 | 详情 |
|------|------|------|
| 事件总线 | `POST/GET/DELETE /admin/listeners` | 所有 dispatch 决策、strata-match 调用、任务链步骤均推送 |
| 管理面板 | `public/sessions.html`、`tasks.html`、`jobs.html` | 5s/10s 自动刷新 |
| 事件日志 | `events.jsonl` | 持久化，供 `/admin/analysis` 离线分析 |
| 日志 | Python logging | 全局 logger + 模块级实例 |

### 降级策略

| 级别 | 条件 | 行为 | 代码 |
|:----:|------|------|------|
| L1 | strata-match 可用 | 完整 Prompt + Tools + Assets | — |
| L2 | strata-match 不可用 | 默认 Prompt + 内置元工具 | `degradation_manager.py` |
| L3 | 下游 LLM 不可用 | 返回 502 | `downstream_llm.py` |

### 可靠性

| 机制 | 说明 |
|------|------|
| 无状态核心 | ComplexityClassifier / ModelSelector / LogicAbstractor 全部无状态 |
| Session 过期清理 | 默认 3 天无活动自动清理（`session_manager.py`） |
| 熔断 | 工具连续失败 3 次后熔断（`tool_dispatcher.py` CircuitBreaker） |
| 降级保底 | 任何外部依赖不可用时，synth-loop 不崩溃 |

---


## 设计原则

| 原则 | 含义 | 体现 |
|------|------|------|
| **分形决策** | 成本按复杂度分形，"hello" 不消耗策略匹配 | `complexity_classifier.py` 规则 + LLM 分层 |
| **策略与执行分离** | synth-loop 管编排，strata-match 管策略，text-cli 管执行 | 三层解耦架构 |
| **降级优先于不可用** | 外部依赖不可用时自动降级 | `degradation_manager.py` 三层降级 |
| **单一真相来源** | 规则→yaml，模型→yaml，配置→yaml | `complexity_rules.yaml`、`model_config.yaml`、`config.yaml` |
| **无状态组件优先** | 核心决策组件不持有状态 | ComplexityClassifier / ModelSelector / LogicAbstractor |
| **Dispatch 是模式不是 API** | 嵌入已有端点，不增新路由 | 分形决策嵌入 `/v1/chat/completions` 内部 |


---
