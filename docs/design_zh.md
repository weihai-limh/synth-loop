# synth-loop 设计文档

> **文档类型**：技术设计
> **版本**：v0.1.2 | **日期**：2026-07-23
> **适用范围**：synth-loop
> **关联文档**：`product_zh.md`、`api_zh.md`
>
> 本文档回答「工程上怎么做」。所有设计以代码真相为依据。

---

## 一、核心定位

synth-loop 是一个 **LLM 编排引擎**——对每次请求做分类、路由、策略注入、任务拆解和上下文累积。它对外暴露 OpenAI/Anthropic 兼容端点以消除接入摩擦，但内部行为不是透传——是编排。

```
API 代理：请求 → 转发 → 响应（不改语义）
synth-loop：请求 → 复杂度分类 → 分形路由 → 策略注入 → 任务链/直答 → LLM → 流式返回
```

### 是什么 / 不是什么

| 是 | 不是 |
|------|------|
| 编排引擎——分类、路由、注入、拆解、执行（`src/app/services/execution_router.py`） | 匹配引擎（策略匹配由外部策略服务负责） |
| 协议兼容端点——OpenAI + Anthropic 双协议接入（`src/app/services/protocol_translator.py`） | API 代理——不做请求透传，每个请求都经历编排管线 |
| 上下文累积与注入——XML 标签体系 + 永久区管理（`src/app/services/context_injector.py`） | LLM 框架（不封装 LLM 调用） |
| 编排决策者——路由选择、工具调度、任务推进 | 策略持有者（策略由外部策略服务管理） |

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

**设计依据**（`src/app/config.py` `PROJECT_ROOT` / `DEPLOY_DIR` / `SRC_DIR` 路径常量）：三组件通过 HTTP 解耦，每层可独立演进、独立替换。synth-loop 消费 strata-match 输出，不依赖其内部实现；可降级运行。

### 2.2 平面/分层

| 平面 | 组件 | 职责 | 代码位置 |
|------|------|------|---------|
| **用户面** | 外部客户端 | 通过 OpenAI/Anthropic 协议发起请求 | 外部 |
| **编排面** | synth-loop | 分形决策、策略注入、任务链推进、SSE 流式 | `src/app/` |
| **策略面** | strata-match | Prompt 匹配、skills 技能分片、工具定义、Assets | 外部服务 |
| **执行面** | text-cli | 分布式指令执行、能力发现 | 外部服务 |
| **管理面** | 管理面板 + 事件总线 | 会话监控、任务链追踪、Job 管理 | `src/public/` + `src/app/routers/admin.py` |

### 2.3 外部依赖接口

| 外部服务 | 端点 | 鉴权 | 调用范式 | 代码引用 |
|---------|------|------|---------|---------|
| strata-match | `POST /api/v1/query` | 无（内网） | HTTP JSON request/response | `src/app/services/strata_match_client.py` |
| strata-match | `POST /api/v1/users` | 无 | HTTP JSON（联动注册） | `src/app/routers/admin.py` |
| strata-match | `POST /api/v1/jobs` | 无 | HTTP JSON（open/close） | `src/app/services/job_store.py` |
| 下游 LLM | `POST /v1/chat/completions` | API Key | OpenAI 兼容 HTTP | `src/app/services/downstream_llm.py` |
| text-cli | `POST /text-cli/cli` | 无（内网） | HTTP JSON | `src/app/services/textcli_client.py` |

---

## 三、主线服务设计

### 3.1 路由层（`src/app/routers/`）

| 能力 | 实现 | 说明 |
|------|------|------|
| OpenAI 入口 | `chat.py` — `chat_completions()` + dispatch 决策链 | `/v1/chat/completions` |
| Anthropic 入口 | `anthropic_chat.py` — 请求翻译 + dispatch | `/v1/messages` |
| 数据面包 | `packets.py` — 上下文数据包提交 + 校验 | `/v1/packets`（v0.1.1 新增） |
| 健康检查 | `health.py` | `/health` |
| 异步任务 API | `tasks.py` — GET + POST cancel | `/api/v1/tasks/{id}` |
| 管理面板 | `admin.py` — HTML 页面路由 | `/admin/sessions` 等 |

### 3.2 编排服务层（`src/app/services/`）

| 能力 | 实现 | 说明 |
|------|------|------|
| 复杂度分类 | `complexity_classifier.py` | 规则匹配 → chat / task_chain / fractal |
| 执行路由 | `execution_router.py` | 分形决策 + 模型选择 + 下游调用编排 |
| 任务链执行器 | `task_chain_executor.py` | plan → execute → verify → summarize |
| 内部推理器 | `internal_reasoner.py` | 步骤拆解 + 验证逻辑 |
| 上下文注入 | `context_injector.py` | XML 标签体系上下文组装 |
| 上下文压缩 | `context_compressor.py` | 上游过滤——按复杂度三态处理 system 消息 |
| 上下文标签管理 | `context_manager.py` | 按标签 load/unload/list/refresh 管理永久区上下文 |
| 流式处理 | `streaming_handler.py` | OpenAI + Anthropic SSE 格式输出 |
| 协议翻译 | `protocol_translator.py` | Anthropic ↔ OpenAI 格式互转 |
| strata-match 客户端 | `strata_match_client.py` | HTTP 客户端 + 缓存 + mock |
| 工具适配器 | `strata_match_tool_adapter.py` | strata-match 工具 → OpenAI 格式 |
| 工具分发器 | `tool_dispatcher.py` | 注册 + 路由工具调用 |
| 动态工具执行 | `dynamic_tool_executor.py` | 运行时工具执行 |
| 降级管理器 | `degradation_manager.py` | 三层降级逻辑 |
| 模型选择器 | `model_selector.py` | 按复杂度选模型 |
| 逻辑抽象器 | `logic_abstractor.py` | 关键词判定 subtype |
| 会话管理器 | `session_manager.py` | Session CRUD + 过期清理 |
| DB 写入器 | `db_writer.py` | 异步事件日志写入 |
| Job 存储 | `job_store.py` | 跨组件 Job 协同 |
| Packet 存储 | `packet_store.py` | 内存缓存 + TTL 自动清理 + type 校验（v0.1.1 新增） |
| 预处理器 | `preprocessors.py` | 按 type 分发预处理器提取摘要（v0.1.1 新增） |

### 3.3 工具层（`src/app/tools/`）

| 能力 | 实现 | 说明 |
|------|------|------|
| 专家 Prompt 选择 | `select_system_prompt.py` | 根据意图选人设 |
| 文档加载 | `load_document.py` | 加载到永久上下文区 |
| 文档卸载 | `unload_document.py` | 从上下文区移除 |
| text-cli 发现 | `discover_textcli.py` | 发现可用指令 |
| text-cli 调用 | `call_textcli.py` | 执行指令 |
| 上下文标签管理 | `context_manager.py` | 按标签管理永久区上下文 |

---

## 四、数据流设计

### 4.1 请求流（热路径）

```
客户端 → POST /v1/chat/completions
  │
  ├── [可选的] auth 中间件 → x-synthloop-user-id 校验 → 401 或继续
  │    代码: src/app/middleware/auth.py
  │
  ├── [可选的] 会话复用 → session_manager.get_or_create()
  │    代码: src/app/services/session_manager.py
  │
  ├── 消息前置检查层
  │     ├── Task-(.+)-synthloop 匹配 → 查 tasks 表 → 终点响应
  │     └── <user-memory>...</user-memory> 匹配 → 提取 → 写入永久区
  │    代码: src/app/routers/chat.py chat_completions()
  │
  ├── 复杂度分类
  │     ├── 层1: 规则匹配（<1ms, 0 token）
  │     └── 层2: 分形 Prompt（1 次 LLM 调用）
  │    代码: src/app/services/complexity_classifier.py
  │
  ├── 分形路由
  │     ├── a/chat → 直答
  │     ├── b/prompt_chat → strata-match 策略查询 → 注入 → LLM
  │     ├── c/task → strata-match 工具注入 → LLM 工具调用循环
  │     └── e,f/task_chain → 任务链拆解执行
  │    代码: src/app/routers/chat.py chat_completions() dispatch 决策链
  │
  ├── 下游 LLM 调用
  │    代码: src/app/services/downstream_llm.py
  │
  └── SSE 流式响应
       代码: src/app/services/streaming_handler.py
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
  │  src/app/config.py               ├── get_config() → 全局缓存
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
  └── 推理: downstream_llm.chat() / task_chain_executor.execute()
```

---

## 五、统一终端契约

### 对外 API 端点

| 端点 | 协议 | 方法 | 鉴权 | 代码 |
|------|------|------|------|------|
| `/v1/chat/completions` | OpenAI | POST | 无（可选 Bearer） | `chat.py` |
| `/v1/messages` | Anthropic | POST | 无（可选 x-api-key） | `anthropic_chat.py` |
| `/v1/packets` | JSON | POST | 无 | `packets.py`（v0.1.1） |
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

> 完整契约定义见版本归档中的 `functional_design/contract_zh.md`

---

## 六、媒介层设计

### 6.1 媒介-系统平面调用矩阵

| 媒介 | 编排面 | 策略面 | 执行面 | 管理面 |
|------|:------:|:------:|:------:|:------:|
| OpenAI SDK 客户端 | ✅ | — | — | — |
| Anthropic SDK 客户端 | ✅ | — | — | — |
| cURL / HTTP | ✅ | — | — | — |
| 管理面板浏览器 | — | — | — | ✅ |

### 6.2 媒介规格

| 媒介 | 入口路径 | 赋能能力 | 战略角色 |
|------|---------|---------|---------|
| OpenAI 客户端 | `base_url=http://localhost:13155/v1` | 分形决策 + 策略注入 + 流式 | 主入口 |
| Anthropic 客户端 | `base_url=http://localhost:13155` | 分形决策 + 策略注入 + 流式翻译 | 兼容入口 |
| 管理面板 | `http://localhost:13155/admin/*` | 会话/任务链/Job 可视化管理 | 运维 |

---

## 七、配置与持久化设计

### 7.1 配置文件拓扑

```
src/
├── config.yaml            ← 主配置（服务、auth、session_memory、async_tasks）
├── model_config.yaml      ← 模型端点池 + LLM 路由
└── complexity_rules.yaml  ← 分形规则（仅覆盖两端极值）

src/
└── data/
    └── gateway.db         ← SQLite 持久化（aiosqlite）
```

### 7.2 配置表

| 配置段 | 文件 | 默认值 | 代码消费方 |
|--------|------|--------|-----------|
| `strata_match` | `config.yaml` | url=localhost:13156, mock=false | `strata_match_client.py` |
| `textcli` | `config.yaml` | default_endpoint=... | `textcli_client.py` |
| `downstream_llm` | `config.yaml` | api_base, api_key, default_model | `downstream_llm.py` |
| `auth` | `config.yaml` | enabled=false, required=false | `middleware/auth.py` |
| `session_memory` | `config.yaml` | enabled=true | `routers/chat.py` |
| `async_tasks` | `config.yaml` | enabled=false, max_per_user=3 | `routers/chat.py` |
| `packets` | `config.yaml` | enabled=true, ttl_seconds=1800 | `packet_store.py`（v0.1.1） |
| `endpoints` | `model_config.yaml` | 端点池定义 | `execution_router.py` |
| `llm_routing` | `model_config.yaml` | 路由映射 | `execution_router.py` |
| `rules` | `complexity_rules.yaml` | chat/task_chain 规则 | `complexity_classifier.py` |

### 7.3 持久化

| 表 | 文件 | 用途 | 记录数上限 |
|----|------|------|:---------:|
| `session_snapshots` | `gateway.db` | 会话持久化（permanent_system_prompt, temp_history, snapshot） | 无 |
| `events` | `events.jsonl` | 事件日志 | 无 |
| `users` | `gateway.db` | 用户认证（v0.1.1） | 无 |
| `tasks` | `gateway.db` | 异步任务（v0.1.1） | 无 |

---

## 八、安全设计

### 8.0 威胁假设

| 假设 | 影响 | 当前措施 |
|------|------|---------|
| 部署在内网，外部不可直达 | 低——内网隔离 | 无额外认证（出厂默认） |
| 恶意客户端伪造 user-id | 中——多租户场景 | `auth.enabled=true, required=true` 时强制校验 |
| 下游 LLM API Key 泄露 | 高——财务损失 | Key 配在 config.yaml 中，建议环境变量注入 |
| Prompt 注入 | 中——越狱风险 | 无专门检测（v0.2 计划） |

**最坏情况推演**：config.yaml 泄露 → 攻击者可调用下游 LLM 产生费用。缓解：生产环境使用 `${ENV_VAR}` 环境变量注入（`_resolve_env_vars()` 内置支持，见 `src/app/config.py`）。

### 8.1 网络分层 / 终端安全 / 隐私合规

| 维度 | 措施 |
|------|------|
| 网络分层 | `auth.enabled` 配置控制，默认关闭（开箱即用） |
| 敏感信息 | 代码中无硬编码密钥（D1-D5 纪律红线 D5 约束对外措辞） |
| Session 隔离 | `x-synthloop-session-id` 隔离会话，`x-synthloop-user-id` 隔离用户 |

---

## 九、非功能性设计

### 9.1 可观测性

| 能力 | 实现 | 详情 |
|------|------|------|
| 事件总线 | `POST/GET/DELETE /admin/listeners` | 所有 dispatch 决策、strata-match 调用、任务链步骤均推送 |
| 管理面板 | `public/sessions.html`、`tasks.html`、`jobs.html` | 5s/10s 自动刷新 |
| 事件日志 | `events.jsonl` | 持久化，供 `/admin/analysis` 离线分析 |
| 日志 | Python logging | 全局 logger + 模块级实例 |

### 9.2 降级策略

| 级别 | 条件 | 行为 | 代码 |
|:----:|------|------|------|
| L1 | strata-match 可用 | 完整 Prompt + Tools + Assets | — |
| L2 | strata-match 不可用 | 默认 Prompt + 内置元工具 | `degradation_manager.py` |
| L3 | 下游 LLM 不可用 | 返回 502 | `downstream_llm.py` |

### 9.3 可靠性

| 机制 | 说明 |
|------|------|
| 无状态核心 | ComplexityClassifier / ModelSelector / LogicAbstractor 全部无状态 |
| Session 过期清理 | 默认 3 天无活动自动清理（`session_manager.py`） |
| 熔断 | 工具连续失败 3 次后熔断（`tool_dispatcher.py` CircuitBreaker） |
| 降级保底 | 任何外部依赖不可用时，synth-loop 不崩溃 |

---

## 十、乘数效应结构

| 基础设施 | 乘数产品 |
|---------|---------|
| 分形决策（`complexity_classifier.py`） | 按请求复杂度选择最经济的执行路径，简单请求零策略开销 |
| 策略注入（`strata_match_client.py`） | 无需手写 Prompt，自动匹配专家人设 |
| 任务链推进（`task_chain_executor.py`） | 复杂任务自动拆解，无需手动分步调用 |
| SSE 双协议（`streaming_handler.py`、`protocol_translator.py`） | 兼容两大生态，零成本接入 |
| 可观测性（`admin.py` + `public/`） | 全链路可视化，降低调试成本 |

---

## 十一、版本契约

| 版本 | 验收标准 | 里程碑定位 |
|------|---------|-----------|
| v0.1 | 112/112 静态测试 PASS，dynamic 全部通过 | 基线版本——功能完整度 |
| v0.1.1 | 189 静态测试 PASS，9 动态脚本就绪 | 基础设施版本——用户系统 + 分形深化 |
| v0.1.2 | 管道引擎（PipelineSession + 状态机 + 计划编译器 + 异步委托 + 9 端点 API） | 质变版本——相位管道大脑 |
| v0.2（规划） | 质量反馈分析 + 路由准确率可观测 | 闭环版本——骨架填肉 |

---

## 十二、已知偏差与技术债

### 偏差表

| 偏差 | 影响 | 原因 |
|------|------|------|
| `_check_cancelled()` 使用 aiosqlite 同步查询 | 高频场景有性能隐患 | 骨架阶段简化实现 |
| `FRACTAL_SYSTEM_PROMPT` 硬编码在 `chat.py` | prompt 改动需改代码 | 未配置化 |
| DB 访问模式不一致（本地 import vs 全局） | 可维护性问题 | 历史遗留 |

### 代码债表

| 位置 | 债务 | 计划版本 |
|------|------|:-------:|
| `task_chain_executor.py` | `_check_cancelled()` aiosqlite 同步查询 | v0.2 |
| `chat.py` | `FRACTAL_SYSTEM_PROMPT` 硬编码英文 | v0.2 |
| `chat.py` | `_create_async_task()` 本地 import aiosqlite | v0.2 |

---

## 十三、架构预留

以下能力计划在后续版本交付：

| 能力 | 架构中的设计位 | 计划版本 |
|------|------|:---:|
| 制品收集 CDN 落地 | 管道每相位产出物经 CDN 分发 | v0.1.3 |
| 物理安全/人授权激活 | 物理操作相位的播片审批 + 安全规则 | v0.1.3 |
| 路由准确率可观测 | 分形决策路由的准确性指标收集与可视化 | v0.2 |
| 质量反馈分析 | feedback 数据沉淀后的分析优化逻辑 | v0.2 |

---

## 十四、测试架构

### 测试分层

| 层 | 位置 | 运行条件 | 覆盖内容 |
|----|------|---------|---------|
| 静态测试 | 离线 pytest | 逻辑正确性（正则、状态机、配置、分支） |
| 动态测试 | 需服务运行中 | 端到端行为（Header 读写、SSE、页面） |

### 冒烟测试定义

服务启动后，执行以下 curl 确认基本可用：

```bash
curl http://localhost:13155/health
# → {"status": "ok", "version": "0.1.0"}

curl -s http://localhost:13155/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"deepseek-v4-flash","messages":[{"role":"user","content":"你好"}]}'
# → 返回含 choices 的 JSON
```

---

## 十五、设计原则

| 原则 | 含义 | 体现 |
|------|------|------|
| **分形决策** | 成本按复杂度分形，"hello" 不消耗策略匹配 | `complexity_classifier.py` 规则 + LLM 分层 |
| **策略与执行分离** | synth-loop 管编排，strata-match 管策略，text-cli 管执行 | 三层解耦架构 |
| **降级优先于不可用** | 外部依赖不可用时自动降级 | `degradation_manager.py` 三层降级 |
| **单一真相来源** | 规则→yaml，模型→yaml，配置→yaml | `complexity_rules.yaml`、`model_config.yaml`、`config.yaml` |
| **无状态组件优先** | 核心决策组件不持有状态 | ComplexityClassifier / ModelSelector / LogicAbstractor |
| **Dispatch 是模式不是 API** | 嵌入已有端点，不增新路由 | 分形决策嵌入 `/v1/chat/completions` 内部 |

---

_文档版本：v1.0｜2026-07-15｜新增 §十三 架构预留_
