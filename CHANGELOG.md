# CHANGELOG

## [0.1.1] - 2026-07-06

### 新增
- 用户系统（`x-synthloop-user-id` Header 认证，三层开关控制）
- 6 级分形路由（a-f 单字母输出）
- 消息前置检查（Task-ID 查询 + user-memory 提取）
- 上下文数据面（`POST /v1/packets` + `packets` 请求字段）
- 异步任务骨架（tasks 表 + `POST /api/v1/tasks/{id}/cancel`）
- 管理面板用户管理页面

### 变更
- Header 重命名：`x-gateway-session-id` → `x-synthloop-session-id`（破坏性变更，不留向后兼容）

### 修复
- 静态测试从 112 扩展到 189 用例，覆盖用户系统、分形格式、认证逻辑、并发限制

## [0.1] - 2026-06

### 新增
- 初始版本：LLM 编排引擎
- 分形决策（规则 + LLM 双层分类）
- 策略注入（strata-match 查询）
- 任务链执行（plan → execute → verify → summarize）
- OpenAI + Anthropic 双协议 SSE 流式
- 管理面板（会话监控、任务链监控、Job 管理）
- 三层降级（L1 完整 / L2 默认策略 / L3 502）
