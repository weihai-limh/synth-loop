# CHANGELOG

## [0.1.2] - 2026-07-21

### 新增
- **管道引擎**：PipelineSession 数据模型 + 管道/相位双状态机（T1~T4）
- **相位感知注入管线**：三步管线（取 tools → 取策略 → LLM 注入产出）（T5）
- **计划编译器**：PlanConfig → text-cli path JSON，双输出模式（编辑/直通）（T6）
- **管道 API**：9 端点 REST API（创建/确认/启动/查询/暂停恢复中止/路径确认/审批/驳回）（T7）
- **异步委托 text-cli**：委托 text-cli task_manager 执行相位 + 轮询状态（T8）
- **T11 预埋**：PipelineSession 预留 V0.1.3 字段（waiting_human_authorization/物理安全/成本追踪）

### 修复
- **可靠性底座**：校验异常不再静默 passed，步骤异常以 StepExecutionError 上抛
- **DB 连接收敛**：全局共享 aiosqlite 连接（lifespan 初始化），消除循环内重复建连
- **并发上限**：`_check_concurrency_limit` 从骨架 `return True` 改为真实 DB 计数

### 变更
- **FRACTAL_SYSTEM_PROMPT 配置化**：从 `config/fractal_prompt.txt` 加载
- **异步骨架 → 委托**：删除 `_create_async_task` 空转 → `_delegate_to_textcli`
- **版本号**：0.1.1 → 0.1.2
- **CORS**：关闭 `allow_credentials`（与 `allow_origins=["*"]` 非法组合修正）
- **测试基线**：pytest + conftest，22 测试用例覆盖核心链路

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
