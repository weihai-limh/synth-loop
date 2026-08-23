# synth-loop API 文档

> 本文档是 synth-loop 的完整 API 参考。如需了解产品定位和使用场景，请参阅 [产品文档](./product_zh.md)。
> 如需了解架构设计，请参阅 [设计文档](./design_zh.md)。

---

## 目录

- [概述](#概述)
- [快速上手](#快速上手)
- [分形决策与会话管理](#分形决策与会话管理)
- [认证](#认证)
- [错误处理](#错误处理)
- [API 端点](#api-端点)
  - [聊天补全（OpenAI 格式）](#聊天补全openai-格式)
  - [消息创建（Anthropic 格式）](#消息创建anthropic-格式)
  - [SSE 流式响应](#sse-流式响应)
  - [健康检查](#健康检查)
  - [统一闸管理（v0.1.2_b）](#统一闸管理v012_b)
  - [永久区数据面（v0.1.2_c）](#永久区数据面v012_c)
- [内置工具](#内置工具)
- [完整场景示例](#完整场景示例)
- [内部接口参考](#内部接口参考)

---

## 概述

synth-loop 提供与 OpenAI 和 Anthropic 完全兼容的 API，客户端只需修改 `base_url` 即可接入。

**Base URL**: `http://localhost:13155`

**支持的 API 格式**：

| 格式 | 端点 | SDK |
|------|------|-----|
| OpenAI | `POST /v1/chat/completions` | `openai` Python/Node.js |
| Anthropic | `POST /v1/messages` | `anthropic` Python/Node.js |
| Packets | `POST /v1/packets` | HTTP JSON（上下文数据包提交） |
| Longdata | `POST/DELETE/GET /v1/longdata` | HTTP JSON（永久区 doc/memory 引入/删除/列出，v0.1.2_c） |

**Content-Type**: `application/json`

**工作模式**：

| 模式 | 条件 | 行为 |
|------|------|------|
| 完整模式 | strata-match 可用 | 自动注入 Prompt + Tools + Assets |
| 降级模式 | strata-match 不可用 | 使用默认 Prompt + 内置工具 |
| 故障模式 | 降级也失败 | 使用兜底 Prompt，标记 error |

**分形决策**：

synth-loop 采用**分形 Prompt** 分级决策，为每次请求**选一条最经济的路径**（v0_1_1: 6 级 a-f）。**注意：相位推理（pk）不走问题分形**——它在分形决策**之前**的消息前置检查层被独立拦截（命中相位 XML 标签即直接路由到相位编排器，永不进入分形路由）：

```
请求 → 消息前置检查层（分形决策之前）
  ├── 相位标签：<tc-phase>目标</tc-phase>           → 结构分形相位（structural）
  ├──          <tc-phase-chain>目标</tc-phase-chain> → 链式相位（chain）
  │     （标签显式锁定；标签内文本为相位目标；无标签普通请求永不自动进相位）
  └── 未命中相位标签 → 进入分形决策 ↓

分形决策 → 规则匹配（免费，<1ms，仅覆盖两端极值）
  ├── "你好"/"hello" → chat（直答，零开销，~235 token）
  └── "先.*再"/"分析并.*生成" → task_chain（任务链推进）

规则未命中 → 分形Prompt（1次LLM调用，单字母输出）→ 选一条：
  ├── a → chat（直答）
  ├── b → prompt_chat（调 strata-match）
  ├── c → task（单次外部工具调用）
  ├── d → sync_task（异步分支，依赖 async_tasks.enabled）
  ├── e → task_chain（异步分支，多步骤任务链）
  └── f → sync_task_chain（同步任务链）
```

选定路径后，上下文经 ck 内核拼装 + 闸监听，推理经 `sl_llm_provider` 唯一落点（_b：所有路径收敛，开闸时可被 ck 闸干预）。

### 会话管理（x-synthloop-session-id）

v0_1_1 起 Header 更名为 `x-synthloop-session-id`（原 `x-gateway-session-id` 不再支持）。

synth-loop 支持跨请求 Session 复用。客户端可通过自定义 HTTP Header `x-synthloop-session-id` 在多轮对话中保持会话状态。

**使用方式**：

| 轮次 | 客户端行为 | synth-loop 响应 |
|------|-----------|-------------|
| 首轮 | 不传 Header 或在 Header 中传空值 | 响应 Header 返回 `x-synthloop-session-id: <uuid>` |
| 后续轮 | 请求 Header 带上 `x-synthloop-session-id: <uuid>` | 复用同一 Session，保持上下文和对话历史 |

**cURL 示例**：

```bash
# 首轮：不传 Header
curl -i http://localhost:13155/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"gpt-4o-mini","messages":[{"role":"user","content":"帮我查北京天气"}]}'
# → 响应 Header: x-synthloop-session-id: 550e8400-e29b-41d4-a716-446655440000

# 后续轮：带上 Session ID
curl -i http://localhost:13155/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "x-synthloop-session-id: 550e8400-e29b-41d4-a716-446655440000" \
  -d '{"model":"gpt-4o-mini","messages":[{"role":"user","content":"上海呢"}]}'
```

**注意**：Session 过期后（默认 3 天无活动）自动清理，需重新开始新 Session。

---

## 快速上手

### 使用 OpenAI SDK

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:13155/v1",
    api_key="any-string"  # synth-loop 不验证客户端 key
)

response = client.chat.completions.create(
    model="gpt-4o-mini",
    messages=[{"role": "user", "content": "帮我写一份智能家居项目的商业计划书"}]
```

### 使用 Anthropic SDK

```python
from anthropic import Anthropic

client = Anthropic(
    base_url="http://localhost:13155",
    api_key="any-string"
)

response = client.messages.create(
    model="claude-3-opus-20240229",
    max_tokens=1024,
    messages=[{"role": "user", "content": "帮我写一份智能家居项目的商业计划书"}]
)
print(response.content[0].text)
```

### 使用 cURL

```bash
# OpenAI 格式
curl http://localhost:13155/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gpt-4o-mini",
    "messages": [{"role": "user", "content": "帮我写一份智能家居项目的商业计划书"}]
  }'

# Anthropic 格式
curl http://localhost:13155/v1/messages \
  -H "Content-Type: application/json" \
  -d '{
    "model": "claude-3-opus-20240229",
    "max_tokens": 1024,
    "messages": [{"role": "user", "content": "帮我写一份智能家居项目的商业计划书"}]
  }'
```

---

## 认证

synth-loop 本身不验证客户端 API Key。客户端可以传递任意值作为 `api_key`。

v0_1_1 起支持 `x-synthloop-user-id` Header 认证，三层行为（`auth.enabled` + `auth.required`）。默认关闭（`auth.enabled=false`），开箱即用。

**v0.1.2_a 起 token 双轨（先验权再归身份）**：

| Header | 作用 | 说明 |
|--------|------|------|
| `x-synthloop-token` | 权限 | 统一 token（user/service/admin scope，sha256 hash 校验），`tokens` 表签发 |
| `x-synthloop-user-id` | 身份 | `sl-{uuid}`，透传给上游做身份映射（sm 侧 `map_user_id` → `sm-{uuid}`） |

- **OpenAI 格式**：`Authorization: Bearer <any-string>`（可选）
- **Anthropic 格式**：`x-api-key: <any-string>`（可选）
- **用户认证**：`x-synthloop-user-id: sl-{uuid}`（v0_1_1 新增，可选）
- **权限认证**：`x-synthloop-token: <token>`（v0.1.2_a 新增，可选）
- **管理面**：`/api/v1/runtime-endpoints` CRUD 要求 **admin scope**（3.12），普通 user/service token → 403

synth-loop 使用配置文件中的 `downstream_llm.api_key` 调用下游 LLM。

---

## 错误处理

### 错误响应格式

```json
{
  "error": {
    "message": "错误描述",
    "type": "error_type",
    "code": "error_code"
  }
}
```

### HTTP 状态码

| 状态码 | 说明 |
|--------|------|
| 200 | 成功 |
| 400 | 请求参数错误 |
| 500 | 内部服务器错误 |
| 502 | 下游 LLM 调用失败 |
| 503 | 服务不可用（所有降级策略耗尽） |

### 降级行为

| 场景 | 行为 |
|------|------|
| strata-match 超时 | 自动降级到默认 Prompt |
| strata-match 返回错误 | 自动降级到默认 Prompt |
| 工具调用失败 | 注入错误信息，LLM 自行处理 |
| 工具连续失败 3 次 | 熔断，后续调用自动降级 |
| 下游 LLM 不可用 | 返回 502 错误 |

---

## API 端点

### 聊天补全（OpenAI 格式）

```
POST /v1/chat/completions
```

完全兼容 [OpenAI Chat Completions API](https://platform.openai.com/docs/api-reference/chat)。

#### 请求参数

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| model | string | 是 | 模型名称（synth-loop 会使用配置的下游模型） |
| messages | array | 是 | 消息数组 |
| temperature | float | 否 | 采样温度（0-2） |
| max_tokens | integer | 否 | 最大生成 token 数 |
| tools | array | 否 | 工具定义（synth-loop 会合并动态工具） |
| tool_choice | string | 否 | 工具选择策略 |
| stream | boolean | 否 | 是否流式返回 |
| packets | string[] | 否 | **v0_1_1 新增**：已提交到 `/v1/packets` 的 packet ID 列表 |
| inline_data | object[] | 否 | **v0_1_1 新增**：降级模式下原始数据直接内联，无需先提交 |
| synth_pipeline | object | 否 | **v0.1.2_a 新增**：相位状态字段 `{id, action}`——显式驱动相位多轮推进（confirm/reject/regenerate/regenerate_with_new_context/abort/check_result）；响应中携带 `{id, step, phase_index, phase_total, artifact_ref}`，调用方原样回传以继续。**相位触发（_b 标签机制）**：首轮用 `<tc-phase>目标</tc-phase>`（结构分形 structural，复杂任务）或 `<tc-phase-chain>目标</tc-phase-chain>`（链式分形 chain，中等任务）显式触发；标签内文本为相位目标；无标签普通请求永不自动进相位 |

#### messages 数组

| role | 说明 |
|------|------|
| system | 系统提示词（synth-loop 会与 strata-match 返回的 Prompt 合并） |
| user | 用户消息 |
| assistant | 助手消息 |
| tool | 工具调用结果 |

#### 请求示例

```json
{
  "model": "gpt-4o-mini",
  "messages": [
    {"role": "user", "content": "帮我写一份智能家居项目的商业计划书"}
  ],
  "temperature": 0.7,
  "max_tokens": 1000
}
```

#### 响应示例

```json
{
  "id": "chatcmpl-gw-001",
  "object": "chat.completion",
  "created": 1719312000,
  "model": "gpt-4o-mini",
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content": "# 智能家居项目商业计划书\n\n## 一、项目概述\n\n本项目旨在打造一套全屋智能家居系统，通过物联网技术将家庭设备互联互通...\n\n## 二、市场分析\n\n随着5G和AI技术的普及，智能家居市场规模预计2026年将达到5000亿元..."
      },
      "finish_reason": "stop"
    }
  ],
  "usage": {
    "prompt_tokens": 150,
    "completion_tokens": 200,
    "total_tokens": 350
  }
}
```

#### 带工具调用的响应

当 synth-loop 注入了动态工具，LLM 可能返回工具调用：

```json
{
  "id": "chatcmpl-gw-033",
  "object": "chat.completion",
  "created": 1719313920,
  "model": "gpt-4o-mini",
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content": null,
        "tool_calls": [
          {
            "id": "call_weather_001",
            "type": "function",
            "function": {
              "name": "api_weather_query",
              "arguments": "{\"city\": \"北京\"}"
            }
          }
        ]
      },
      "finish_reason": "tool_calls"
    }
  ],
  "usage": {
    "prompt_tokens": 150,
    "completion_tokens": 40,
    "total_tokens": 190
  }
}
```

synth-loop 会自动执行工具调用，将结果注入推理循环，最终返回文本响应。

#### 开闸响应（gate: pending，v0.1.2_b）

当 `gate_manager` 开启 ck 推理闸（`meta_gate: on/auto`）时，请求上下文会被 ck park——响应不直接出结果，而是返回待闸状态（供外挂服务/调用方 peek/amend 干预后放行，为上下文自动化优化留可能）：

```json
{
  "id": "chatcmpl-gate-a1b2c3d4",
  "object": "chat.completion",
  "model": "gate-pending",
  "choices": [{"index": 0, "message": {"role": "assistant", "content": "上下文已提交推理闸（gate=pending）..."}, "finish_reason": "stop"}],
  "gate": "pending",
  "context_id": "a1b2c3d4...",
  "context": {"region_index": {...}}
}
```

干预流程：`GET /chatgate/{context_id}`（peek）→ `POST /chatgate/{context_id}`（amend）→ 放行出结果。`gate_manager` 默认 `all_off`（关闸直推），仅显式切换后才开闸。

---

### 消息创建（Anthropic 格式）

```
POST /v1/messages
```

完全兼容 [Anthropic Messages API](https://docs.anthropic.com/en/api/messages)。

#### 请求参数

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| model | string | 是 | 模型名称 |
| max_tokens | integer | 是 | 最大生成 token 数 |
| messages | array | 是 | 消息数组 |
| system | string | 否 | 系统提示词 |
| temperature | float | 否 | 采样温度 |
| tools | array | 否 | 工具定义 |
| stream | boolean | 否 | 是否流式返回 |

#### 请求示例

```json
{
  "model": "claude-3-opus-20240229",
  "max_tokens": 1024,
  "system": "你是一个有帮助的AI助手。",
  "messages": [
    {"role": "user", "content": "帮我写一份智能家居项目的商业计划书"}
  ]
}
```

#### 响应示例

```json
{
  "id": "msg-gw-001",
  "type": "message",
  "role": "assistant",
  "content": [
    {
      "type": "text",
      "text": "# 智能家居项目商业计划书\n\n## 一、项目概述\n\n本项目旨在打造一套全屋智能家居系统，通过物联网技术将家庭设备互联互通..."
    }
  ],
  "model": "claude-3-opus-20240229",
  "stop_reason": "end_turn",
  "usage": {
    "input_tokens": 150,
    "output_tokens": 200
  }
}
```

---

### SSE 流式响应

synth-loop 完整支持 OpenAI 和 Anthropic 双协议的 SSE（Server-Sent Events）流式输出。客户端只需在请求中设置 `stream: true`。

#### OpenAI 格式 SSE

**请求**：

```bash
curl -N http://localhost:13155/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gpt-4o-mini",
    "stream": true,
    "messages": [{"role": "user", "content": "你好"}]
  }'
```

**响应格式**（SSE data 行，逐块返回）：

```
data: {"id":"chatcmpl-gw-001","object":"chat.completion.chunk","created":1719312000,"model":"gpt-4o-mini","choices":[{"index":0,"delta":{"role":"assistant"},"finish_reason":null}]}

data: {"id":"chatcmpl-gw-001","object":"chat.completion.chunk","choices":[{"index":0,"delta":{"content":"你"},"finish_reason":null}]}

data: {"id":"chatcmpl-gw-001","object":"chat.completion.chunk","choices":[{"index":0,"delta":{"content":"好"},"finish_reason":null}]}

data: {"id":"chatcmpl-gw-001","object":"chat.completion.chunk","choices":[{"index":0,"delta":{"content":"！"},"finish_reason":"stop"}]}

data: [DONE]
```

#### Anthropic 格式 SSE

Anthropic 协议使用 `event:` 行 + `data:` 行的格式：

```
event: message_start
data: {"type":"message_start","message":{"id":"msg-gw-001","type":"message","role":"assistant","model":"claude-3-haiku-20240307","content":[],"usage":{"input_tokens":15,"output_tokens":1}}}

event: content_block_start
data: {"type":"content_block_start","index":0,"content_block":{"type":"text","text":""}}

event: content_block_delta
data: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"你"}}

event: content_block_delta
data: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"好"}}

event: content_block_stop
data: {"type":"content_block_stop","index":0}

event: message_delta
data: {"type":"message_delta","delta":{"stop_reason":"end_turn"},"usage":{"output_tokens":3}}

event: message_stop
data: {"type":"message_stop"}
```

**注意事项**：
- Anthropic 入口的模型名会通过 `anthropic_model_map` 自动映射为下游 OpenAI 模型
- 分形决策 + strata-match 查询在首块输出前同步完成，不影响流式延迟
- OpenAI → Anthropic 下游 SSE（即上游用 OpenAI 格式、下游用 Anthropic 模型）计划在后续版本支持

---

### 上下文数据包（v0_1_1 新增）

```
POST /v1/packets
```

提交上下文数据包。调用方可在 `/v1/chat/completions` 或 `/v1/messages` 之前先提交数据包，之后在请求中通过 `packets:[id]` 引用，数据经预处理器生成摘要后自动注入 system prompt。

#### 请求参数

| 参数 | 类型 | 必填 | 说明 |
|------|------|:----:|------|
| source | string | 是 | 来源标识符（`browser` / `im` / `mini-program` / `esp32` / ...） |
| type | string | 是 | packet 类型（见 type 注册表） |
| payload | object | 是 | 按 type 定义的数据体 |
| meta | object | 否 | 附加元数据 |

#### 约束

| 约束 | 值 |
|------|-----|
| 单 packet 最大体积 | 5 MB |
| packet TTL | 默认 30 分钟（可配置 `packets.ttl_seconds`） |
| 未知 type | 400 |
| 超体积 | 413 |

**type 注册表**：`browser_dom` / `browser_selection` / `browser_meta` / `browser_structure` / `browser_audio` / `wechat_context` / `im_thread` / `im_message_history` / `packet_consent` / `aiot_sensor` / `device_status` / `rpi_sensor`(预留) / `camera_frame`(预留)

#### 请求示例

```json
{
  "source": "browser",
  "type": "browser_dom",
  "payload": {
    "html": "<html><title>示例页面</title><body><h1>标题</h1><p>正文内容...</p></body></html>"
  }
}
```

#### 响应示例

```json
{
  "packet_id": "pkt_a1b2c3d4e5f6g7h8"
}
```

#### 使用流程

```
1. POST /v1/packets → packet_id
2. POST /v1/chat/completions { "packets":["pkt_xxx"], "messages":[...] }
   → synth-loop 从 PacketStore 取 packet → 预处理器提取摘要 → 注入 system prompt
```

`/v1/messages`（Anthropic 格式）同样支持 `packets` 和 `inline_data` 字段。

#### 降级路径

| 场景 | 行为 |
|------|------|
| packet 已过期（TTL 超） | 忽略该 ID，不阻塞请求 |
| packet type 无对应预处理器 | 跳过预处理，注入原始 payload 截断版（≤200 字符） |
| PacketStore 异常 | 跳过所有 packet 注入，仅处理 inline_data |
| `packets.enabled=false` | packets/inline_data 静默忽略 |

---

### 健康检查

```
GET /health
```

检查服务健康状态。

#### 响应示例

```json
{
  "status": "ok",
  "version": "0.1.0",
  "active_sessions": 42
}
```

---

### 统一闸管理（v0.1.2_b 新增）

> gate_manager 配置面（跨内核闸编排）。供外挂改进服务/调用方查询与切换闸组合。sl 内部闸走组件形态（非 HTTP）。

#### GET /gate-manager/config

查询闸组合注册表 + 各闸开关状态 + ck/pk 挂载态。

```json
{
  "active_combo": "all_off",
  "combos": {
    "decision_only": ["decision"],
    "decision_approval": ["decision", "approval"],
    "intervention_approval": ["intervention", "approval"],
    "meta_all_on": ["meta", "intervention", "approval"],
    "all_off": []
  },
  "meta_gate": "closed",
  "ck_attached": true,
  "pk_attached": true
}
```

#### PATCH /gate-manager/config

切换闸组合 / 控制 ck 闸开关（元闸）。

```json
// 切换闸组合
{"active_combo": "decision_approval"}
// 控制 ck 闸开关（on→auto 允许干预 / off→closed 直推）
{"meta_gate": "on"}
```

| 参数 | 说明 |
|------|------|
| `active_combo` | 切换预制闸组合（未知 → 400） |
| `meta_gate` | `on`/`off`/`auto`——控制 ck 推理闸本身是否参与（on→auto park 可干预 / off→closed 直推） |

**开闸行为**：当 `meta_gate` 为 `on`/`auto` 时，主路径与相位路径的上下文会被 ck park，chat 响应返回 `gate:"pending"` + `context_id`（见聊天补全的 `gate` 字段），可经 `GET/POST /chatgate/{context_id}`（ck 侧）peek/amend 干预后放行。

---

### 永久区数据面（v0.1.2_c 新增）

> 数据面通道B（永久区）：doc/memory 引入到指定会话永久区。与临时区 packets（`/v1/packets`）对称但持久性不同——doc/memory 长期存在于永久区（`loaded_docs` / `permanent_system_prompt`），可被后续会话引用。类型仅 doc/memory 两类，写死。

#### POST /v1/longdata

引入 doc 或 memory 到指定会话永久区。

**请求参数**：

| 字段 | 类型 | 必填 | 说明 |
|------|------|:---:|------|
| session_id | string | 是 | 目标会话 id |
| type | string | 是 | `doc`（文档）或 `memory`（记忆片段） |
| content | string | 是 | 内容（通用文本处理：去首尾空白、压缩连续空行） |

**响应**：

```json
{ "id": "ld_xxxx" }
```

- `type=doc` → 写入 `loaded_docs`（doc_id = 返回 id）
- `type=memory` → 追加到 `permanent_system_prompt`，加 `<user-memory>` 包裹
- `type` 非法或 content 空 → 400

#### DELETE /v1/longdata/{id}

按内部 id 删除永久区 longdata（需 `session_id` 双重校验，防跨会话误删）。

**请求参数**：

| 字段 | 类型 | 必填 | 说明 |
|------|------|:---:|------|
| id | string | 是 | 内部 id（POST 返回） |
| session_id | string | 是 | 目标会话 id（校验归属） |

**响应**：

```json
{ "deleted": true }
```

- id 不存在或 session_id 不匹配 → `{ "deleted": false }`

#### GET /v1/longdata?session_id={id}

列出会话永久区的 longdata。

**响应**：

```json
{
  "session_id": "s1",
  "items": [
    { "id": "ld_xxx", "session_id": "s1", "type": "doc", "content": "...", "created_at": 123 }
  ]
}
```

---

### 任务管理（v0_1_1 新增）

#### GET /api/v1/tasks/{task_id}

查询异步任务状态（仅返回状态，不含结果内容）。

**响应示例**：

```json
{
  "id": "Task-a1b2c3d4-synthloop",
  "status": "running",
  "session_id": "550e8400",
  "user_id": "sl-test-001",
  "created_at": "2026-07-06T10:00:00",
  "updated_at": "2026-07-06T10:01:00"
}
```

#### POST /api/v1/tasks/{task_id}/cancel

取消异步任务。任务状态变为 `cancelled`，TaskChainExecutor 在下一步前中断。

**响应**：200

```json
{
  "id": "Task-a1b2c3d4-synthloop",
  "status": "cancelled"
}
```

---

### 运行时端点管理（v0.1.2_a 新增）

> tc 消费链路配置面。管理 API 要求 **admin scope**（3.12），token 脱敏返回。

#### GET /api/v1/runtime-endpoints

列出运行时端点（token 脱敏）。

```json
{
  "items": [
    {"id": "...", "alias": "home-service", "kind": "runtime",
     "url": "http://10.168.1.151/text-cli/cli", "auth": "none",
     "service_token": "sk-***", "rank": 1, "is_active": 1}
  ],
  "total": 1
}
```

#### POST /api/v1/runtime-endpoints

添加端点。必填 `alias` + `url`；可选 `kind`/`auth`/`service_token`/`access_token`/`rank`/`trust`/`is_active`。同 alias 可多物理行（rank 降级）。

#### PATCH /api/v1/runtime-endpoints/{alias}

更新端点（url/token/rank/is_active 等）。`service_token`/`access_token` 加密落库。

#### DELETE /api/v1/runtime-endpoints/{alias}

删除端点。

---

### 制品数据面（v0.1.2_a 新增）

> 相位产物下行（与 packets 上行对称）。content 只含人读摘要，完整产物经 artifact_ref 获取。

#### GET /api/v1/artifacts/{artifact_id}

获取单个相位产物。

```json
{
  "artifact_id": "art_p1_result_1",
  "pipeline_id": "p1",
  "phase_index": 1,
  "kind": "result",
  "content": "人读摘要...",
  "data": {"output": "..."},
  "created_at": "2026-08-14T03:00:00"
}
```

#### GET /api/v1/artifacts?pipeline_id={id}

按管道列出产物（按 phase_index 排序）。

---

### 管道管理 API（v0.1.2，`pipelines_api.enabled` 默认 false）

> 9 端点管理面：创建/计划确认/启动/查询/暂停恢复中止/路径确认/审批/驳回/相位查询。
> `enabled=false`（默认）时全部 404——对外主契约走 chat（`synth_pipeline` 字段），端点保留给调试/管理。

### 用户管理（v0_1_1 新增）

#### /admin/users

用户管理页面（HTML）。支持创建 `sl-{uuid}` 用户、启用/禁用、删除。创建用户时自动联动注册到 strata-match 的 `sm-{uuid}`。

### 消息前置检查（v0_1_1 新增）

在 dispatch 之前，synth-loop 对用户消息执行两条前置规则：

| 规则 | 匹配模式 | 行为 |
|------|---------|------|
| Task-ID 查询 | `Task-(.+)-synthloop` | 查 tasks 表，返回结果或"任务不存在"，终点 |
| user-memory 提取 | `<user-memory>...</user-memory>` | 提取内容写入 Session 永久区，继续 dispatch |

---

## 内置工具

synth-loop 始终注册以下内置工具，即使 strata-match 不可用：

### select_system_prompt

根据用户意图选择最合适的专家人设 Prompt。

```json
{
  "name": "select_system_prompt",
  "description": "根据用户意图选择最合适的专家人设",
  "parameters": {
    "type": "object",
    "properties": {
      "query": {
        "type": "string",
        "description": "需要匹配意图的文本"
      }
    },
    "required": ["query"]
  }
}
```

### load_document_to_context

加载文档到永久上下文区。

```json
{
  "name": "load_document_to_context",
  "description": "加载文档到永久上下文区",
  "parameters": {
    "type": "object",
    "properties": {
      "doc_name": {
        "type": "string",
        "description": "文档名称（无需路径）"
      },
      "chapter": {
        "type": "string",
        "description": "指定章节或键名（可选）"
      }
    },
    "required": ["doc_name"]
  }
}
```

### unload_document_from_context

从永久上下文中卸载文档。

```json
{
  "name": "unload_document_from_context",
  "description": "从永久上下文中卸载文档",
  "parameters": {
    "type": "object",
    "properties": {
      "doc_id": {
        "type": "string",
        "description": "要卸载的文档ID，由 load_document_to_context 返回"
      }
    },
    "required": ["doc_id"]
  }
}
```

### discover_textcli

发现 text-cli 可用指令，支持关键词过滤。

```json
{
  "name": "discover_textcli",
  "description": "发现 text-cli 可用指令",
  "parameters": {
    "type": "object",
    "properties": {
      "query": {
        "type": "string",
        "description": "关键词过滤（可选）"
      },
      "format": {
        "type": "string",
        "description": "返回格式（可选，默认 compact）"
      }
    }
  }
}
```

### manage_context

按标签管理永久区上下文（load/unload/list/refresh）。

```json
{
  "name": "manage_context",
  "description": "按标签管理永久区上下文",
  "parameters": {
    "type": "object",
    "properties": {
      "action": {
        "type": "string",
        "enum": ["load", "unload", "list", "refresh"],
        "description": "操作类型"
      },
      "tags": {
        "type": "array",
        "items": {"type": "string"},
        "description": "标签列表"
      }
    },
    "required": ["action"]
  }
}
```

### call_textcli

调用 text-cli 指令执行操作。

```json
{
  "name": "call_textcli",
  "description": "调用 text-cli 指令",
  "parameters": {
    "type": "object",
    "properties": {
      "prompt": {
        "type": "string",
        "description": "text-cli 指令，格式：AI:域;动作,参数"
      },
      "endpoint": {
        "type": "string",
        "description": "节点地址（可选，默认自动路由）"
      }
    },
    "required": ["prompt"]
  }
}
```

---

## 完整场景示例

> 以下示例展示 synth-loop 在不同场景下的完整请求/响应。

### 场景 1：纯 Prompt 增强

**请求**：
```bash
curl http://localhost:13155/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gpt-4o-mini",
    "messages": [
      {"role": "user", "content": "帮我写一份智能家居项目的商业计划书"}
    ]
  }'
```

**synth-loop 内部流程**：
1. 调用 strata-match → 返回专家人设 Prompt
2. 注入到 System Prompt
3. 调用下游 LLM

**响应**：
```json
{
  "id": "chatcmpl-gw-001",
  "object": "chat.completion",
  "model": "gpt-4o-mini",
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content": "# 智能家居项目商业计划书\n\n## 一、项目概述\n\n本项目旨在打造一套全屋智能家居系统，通过物联网技术将家庭设备互联互通...\n\n## 二、市场分析\n\n随着5G和AI技术的普及，智能家居市场规模预计2026年将达到5000亿元..."
      },
      "finish_reason": "stop"
    }
  ]
}
```

### 场景 2：Prompt + 工具调用

**请求**：
```bash
curl http://localhost:13155/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gpt-4o-mini",
    "messages": [
      {"role": "user", "content": "帮我查一下北京今天的天气"}
    ]
  }'
```

**synth-loop 内部流程**：
1. 调用 strata-match → 返回 Prompt + 天气查询工具
2. 工具适配并注入
3. LLM 决定调用工具
4. synth-loop 执行工具，结果注入推理
5. LLM 基于结果生成回答

**最终响应**：
```json
{
  "id": "chatcmpl-gw-034",
  "object": "chat.completion",
  "model": "gpt-4o-mini",
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content": "北京今天的天气情况：\n\n**当前天气：**\n- 天气：晴\n- 温度：28°C\n- 湿度：65%\n- 风向：东南风 3级\n\n**温馨提示：**\n今天天气晴朗，温度适中，适合外出活动。"
      },
      "finish_reason": "stop"
    }
  ]
}
```

### 场景 3：Prompt + 资源

**请求**：
```bash
curl http://localhost:13155/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gpt-4o-mini",
    "messages": [
      {"role": "user", "content": "生成毕加索风格的人体图"}
    ]
  }'
```

**synth-loop 内部流程**：
1. 调用 strata-match → 返回 Prompt + Assets（风格参考图 + 人体骨架图）
2. 无工具 → 资源独立注入上下文
3. LLM 知道资源存在，可引用 URL

**响应**：
```json
{
  "id": "chatcmpl-gw-004",
  "object": "chat.completion",
  "model": "gpt-4o-mini",
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content": "我来帮你生成毕加索风格的人体图。\n\n**可用资源：**\n1. 毕加索立体主义风格参考图：https://assets.example.com/picasso_style.png\n2. 站立姿势人体骨架图：https://assets.example.com/standing_pose.json\n\n**生成建议：**\n- 使用毕加索风格参考图作为风格基准\n- 参考站立姿势骨架图进行人体结构构建\n- 采用立体主义的几何分解手法"
      },
      "finish_reason": "stop"
    }
  ]
}
```

### 场景 4：多轮对话

**第 1 轮**：同场景 2

**第 2 轮**：
```bash
curl http://localhost:13155/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gpt-4o-mini",
    "messages": [
      {"role": "user", "content": "帮我查一下北京今天的天气"},
      {"role": "assistant", "content": "北京今天晴，28°C..."},
      {"role": "user", "content": "上海呢"}
    ]
  }'
```

**synth-loop 行为**：
- 检测到多轮对话
- 保持之前的工具注入
- LLM 自动理解"上海呢"指的是查询上海天气

**响应**：
```json
{
  "id": "chatcmpl-gw-036",
  "object": "chat.completion",
  "model": "gpt-4o-mini",
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content": "上海今天的天气情况：\n\n**当前天气：**\n- 天气：多云\n- 温度：32°C\n- 湿度：75%\n- 风向：南风 2级\n\n**两地对比：**\n| 城市 | 温度 | 天气 | 湿度 |\n|------|------|------|------|\n| 北京 | 28°C | 晴 | 65% |\n| 上海 | 32°C | 多云 | 75% |"
      },
      "finish_reason": "stop"
    }
  ]
}
```

### 场景 5：Anthropic 格式

**请求**：
```bash
curl http://localhost:13155/v1/messages \
  -H "Content-Type: application/json" \
  -d '{
    "model": "claude-3-opus-20240229",
    "max_tokens": 1024,
    "messages": [
      {"role": "user", "content": "帮我写一份智能家居项目的商业计划书"}
    ]
  }'
```

**synth-loop 内部流程**：
1. 检测 Anthropic 格式
2. 转译为内部格式
3. 执行与 OpenAI 格式相同的增强流程
4. 将结果转译回 Anthropic 格式

**响应**：
```json
{
  "id": "msg-gw-001",
  "type": "message",
  "role": "assistant",
  "content": [
    {
      "type": "text",
      "text": "# 智能家居项目商业计划书\n\n## 一、项目概述\n\n本项目旨在打造一套全屋智能家居系统..."
    }
  ],
  "model": "claude-3-opus-20240229",
  "stop_reason": "end_turn",
  "usage": {
    "input_tokens": 150,
    "output_tokens": 200
  }
}
```

### 场景 6：相位多轮推理（v0.1.2）

> 相位由 **XML 标签**显式锁定触发：`<tc-phase>`（结构分形 structural）/ `<tc-phase-chain>`（链式分形 chain）。首轮带标签 → 返回 `synth_pipeline`（待规划确认）；后续轮原样回传 `synth_pipeline: {id, action}` 逐相位推进。相位会话按 `synth_pipeline.id`（pipeline_id）定位内存状态，回传时无需额外 Header。

**第 1 轮（首轮触发，结构分形）**：

```bash
curl http://localhost:13155/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "deepseek-v4-flash",
    "messages": [{"role": "user", "content": "<tc-phase>帮我完成一份智能家居项目市场调研报告</tc-phase>"}]
  }'
```

**第 1 轮响应**（`awaiting_plan_confirm`，回传 `synth_pipeline.id` 继续；plan 产物经 `artifact_ref` 取回）：

```json
{
  "id": "chatcmpl-phase-a1b2c3d4",
  "object": "chat.completion",
  "model": "deepseek-v4-flash",
  "choices": [{"index": 0, "message": {"role": "assistant",
    "content": "相位规划如下（共 3 个相位）：\n1. 市场分析\n2. 竞品调研\n3. 报告撰写\n\n请确认（回传 action=confirm）..."}, "finish_reason": "stop"}],
  "usage": {"prompt_tokens": 0, "completion_tokens": 0},
  "synth_pipeline": {
    "id": "p1", "step": "awaiting_plan_confirm",
    "phase_index": 0, "phase_total": 3, "artifact_ref": "art_p1_plan"
  }
}
```

**第 2 轮（确认规划 → 启动管道、生成第一个相位 path）**——回传 `synth_pipeline: {id, action}`：

```bash
curl http://localhost:13155/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "deepseek-v4-flash",
    "messages": [{"role": "user", "content": "确认"}],
    "synth_pipeline": {"id": "p1", "action": "confirm"}
  }'
```

**第 2 轮响应**（`awaiting_path_confirm`，路径确认；`artifact_ref` 为 path 产物——`{"id", "name", "steps"}` 信封，`steps` 为相位可执行步骤，可经数据面取回）：

```json
{
  "id": "chatcmpl-phase-a1b2c3d4",
  "choices": [{"index": 0, "message": {"role": "assistant",
    "content": "相位 1/3「市场分析」的 path 如下：\n{\"id\": \"local\", \"name\": \"市场分析\", \"steps\": [{\"action\": \"execute\", \"description\": \"分析目标市场\"}]}\n\n确认执行（confirm）/ 驳回修改（reject + 意见）/ 中止（abort）。"}, "finish_reason": "stop"}],
  "synth_pipeline": {"id": "p1", "step": "awaiting_path_confirm",
    "phase_index": 0, "phase_total": 3, "artifact_ref": "art_p1_path_0"}
}
```

> `artifact_ref: "art_p1_path_0"` 指向 `{"id","name","steps"}` 的 path 信封（`_compile_path` 产物，由执行体组装；真实部署下 `steps` 为 text-cli 指令序列，当前 LocalExecutor 为占位 execute step）。

**第 3 轮（确认 path → 执行当前相位）**：回传 `{"id": "p1", "action": "confirm"}` → `_confirm` 命中 `awaiting_path_confirm` → `_execute_phase` 执行当前相位。执行走推理缝（SlInferenceSeam → normal routing → sl_llm_provider）。执行完成后若该相位 `require_human_approval` → 进入 `awaiting_approval`（回传 confirm 审批通过 / reject 驳回重试）；否则自动推进下一相位（`awaiting_path_confirm`）直至 `step: "completed"`。

> 链式分形同理，仅触发标签改为 `<tc-phase-chain>`（根相位分形出多相位、子相位直接出 path，钳制深度）。执行经推理缝 LLM；相位上下文可被 ck 闸监听/优化（开闸时）。

---

## 内部接口参考

> 以下接口用于 synth-loop 与 strata-match 之间的通信，仅供参考。

### synth-loop → strata-match

#### POST /api/v1/query

**请求**（完整格式，含任务执行上下文）：

```json
{
  "user_ask": "帮我写一份智能家居项目的商业计划书",
  "types": "role_play",
  "subtypes": "document_writing",
  "context": {"job_id": "sg-chain-001", "step": 1}
}
```

**响应**：

```json
{
  "primary_prompt": "你是一位资深的商业顾问和创业计划专家...",
  "candidates": [],
  "matched_tags": ["商业", "计划书", "智能家居"],
  "matched_skills_tags": ["financial_projection", "market_analysis"],
  "user_ask": "帮我写一份智能家居项目的商业计划书",
  "category": "role_play",
  "subtype": "document_writing",
  "tools": [],
  "assets": []
}
```

**请求字段说明**：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| user_ask | string | 是 | 用户原始提问 |
| types | string | 否 | 主类别（如 `role_play`, `tool_use`，可选） |
| subtypes | string | 否 | 子类别，由 synth-loop 的 LogicAbstractor 判定（如 `document_writing`） |
| context | object | 否 | 任务执行上下文（含 `job_id` 和 `step`，用于任务链场景） |

**响应字段说明**：

| 字段 | 说明 |
|------|------|
| matched_skills_tags | skills-tags 二级匹配结果，用于按细分领域增强 Prompt |
| subtype | strata-match 返回的确认子类别 |

**tools 字段格式**：
```json
{
  "tools": [
    {
      "name": "tc_math_eval",
      "name_cn": "数学计算",
      "subtype": "textcli",
      "description": "计算数学表达式",
      "description_cn": "计算数学表达式",
      "definition": {"command": "AI:tc-math;eval,{expression}"},
      "params": ["expression"],
      "tags": ["数学"],
      "weight": 1.0
    }
  ]
}
```

**assets 字段格式**：
```json
{
  "assets": [
    {
      "name": "picasso_style",
      "name_cn": "毕加索风格",
      "subtype": "image_style",
      "described_cn": "毕加索立体主义风格参考图",
      "url": "https://assets.example.com/picasso_style.png",
      "tags": ["毕加索", "picasso", "立体主义"],
      "weight": 1.0
    }
  ]
}
```

详细接口文档请参阅 [strata-match API.md](../../strata-match/docs/API.md)。

### synth-loop → text-cli

#### POST /text-cli/cli

**请求**：
```json
{
  "prompt": "AI:text-cli;query,compact"
}
```

**响应**：
```json
{
  "rst_types": "text",
  "rst_data": {
    "text": "AI:tc-datetime;now - 获取当前时间\nAI:tc-math;eval,<表达式> - 数学计算\n..."
  }
}
```

---

## 配置参考

完整配置项请参阅 [README.md](../../README.md#配置) 和 [设计文档](./design_zh.md#七配置与持久化设计)。

关键配置：

```yaml
downstream_llm:
  api_base: "https://api.deepseek.com"          # 下游 LLM API 地址
  api_key: "your-api-key"                       # 下游 LLM API Key
  default_model: "deepseek-v4-flash"            # 默认模型

strata_match:
  url: "http://localhost:13156"                  # strata-match 服务地址
  mock: false                                    # Mock 模式（true=不依赖 strata-match 服务）

runtime_endpoints:
  enabled: true                     # 运行时表（v0.1.2_a 取代旧 textcli 段）
  default_alias: "home-service"     # 默认 alias
  seeds: []                         # 种子端点

packets:
  enabled: true                     # packets API 总开关
  ttl_seconds: 1800                 # packet TTL（默认 30 分钟）
  max_packet_size_mb: 5             # 单 packet 最大体积
  max_packets_per_request: 20       # 单次请求最多引用的 packet 数
  max_inline_data_per_request: 10   # 单次 inline_data 最大条数
  types: [browser_structure, browser_dom, ...]   # v0.1.2_c：类型准入完整列表（空时回落内置默认）
```

**模型多场景**（`model_config.yaml`，_b 唯一真源）：`llm_routing` 定义任意场景（chat/prompt_chat/task_chain/analysis/planning/summarize + 未来新增），`model_selector` 直接透传 service 到 `execution_router`——配置加场景即接通，无需改代码。`llm_gateway` 多网关注册默认关闭（`enabled=false`）。

---

*文档版本：v1.2*
*更新时间：2026-08-24 | v0.1.2_c：永久区数据面 /v1/longdata（doc/memory 引入/删除/列出）+ 类型准入进配置 packets.types*
