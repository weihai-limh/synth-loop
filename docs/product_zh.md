# synth-loop 产品文档

> **文档类型**：产品设计
> **版本**：v0.1.2_e | **日期**：2026-08-26
> **适用范围**：synth-loop
> **关联文档**：`design_zh.md`、`api_zh.md`
>
> synth-loop 是一个 **以 LLM 网关形态暴露的任务处理中枢**。对外暴露 OpenAI/Anthropic 兼容端点，对内对每次请求做整套决策（走哪条路径、装什么上下文、过什么闸、用哪个模型、怎么多步推理），并收束到唯一推理落点。

---


## synth-loop 解决什么问题


1. **分类**：判断请求复杂度。简单问候走直接通道，复杂任务走全量增强
2. **路由**：根据复杂度选一条执行路径（直答 / 策略注入 / 工具调用 / 任务链 / 相位推理）
3. **注入**：从策略层拉取匹配的专家 Prompt、技能分片、工具定义，组装上下文
4. **执行**：简单请求直接推理，复杂请求拆成任务链或相位逐步推进，经推理缝收敛到唯一推理落点
5. **相位推理**：复杂任务拆为分形相位树——结构分形（复杂）/链式分形（中等），规划→路径确认→执行→摘要，每相位可闸审查
6. **统一闸**：gate_manager 跨内核编排——相位路径确认/审批（pk 人闸）+ 上下文干预（ck 推理闸）+ 闸开关（元闸），所有 chat 上下文可被闸优化

技术组件（`src/sl-py/app/services/` + `src/sl-py/app/kernels/`）：

| 组件 | 代码 | 职责 |
|------|------|------|
| 复杂度分类 | `complexity_classifier.py` | 规则 + LLM 双层判定 |
| 唯一推理落点 | `sl_llm_provider.py` | 所有路径推理收敛；通用 service 选择 + ck 闸集成 |
| 执行路由 | `execution_router.py` | 分形决策 + 模型选择（多场景透传，llm_routing 配置唯一真源） |
| 上下文内核 | `kernels/context_kernel/`（ vendored） | 六层拼装 + 推理闸 + gate_mode |
| 相位内核 | `kernels/phase_kernel/`（ vendored） | 分形相位树 + 三闸 + 检查点 + 推理缝 + sm 缝（SmStrategyBundle 结构化策略）+ i18n（`i18n/*.json`，sl 单语默认 zh） |
| 推理缝 | `inference_seam.py` | SlInferenceSeam：pk 推理缝，暴露到 build_messages，经 ck 拼装 + 闸 |
| 统一闸 | `gate_manager.py` | 跨内核闸编排：GateType 五类 + 组合函数 + 跨内核循环 |
| 任务链服务 | `task_chain_service.py`（v0.1.2_d 新增，取代已删 `task_chain_executor.py` #6 红线） | 单步闭环：写 tasks 表(queued)→委托 text-cli --async→轮询→确认闸(内部 `_dispatch_confirm`)→回写(completed/error)，承接 G3 落库责任 |
| 上下文注入 | `context_injector.py` | 任务链步骤上下文注入（已完成步骤 + 当前步骤） |
| 协议翻译 | `protocol_translator.py` | Anthropic ↔ OpenAI 格式互转 |
| 降级管理器 | `degradation_manager.py` | 三层降级逻辑 |
| 相位编排器 | `phase_chat_orchestrator.py` | chat 多轮契约（_e：planner 接 sm=PhasePlanPlanner，从 config.strata_match.url 取地址；`handle(..., lang="zh")` 单语硬编码） |

---

## 三步开始用

### 🟢 快速通道（2 分钟）

```bash
# Windows 解包后
deploy/win/synth-loop-v0.1.2/start.bat

# Linux 解包后
bash deploy/linux/synth-loop-v0.1.2/start.sh

# 容器（装有 Docker 的机器）
python scripts/release/container/build.py
docker run -d -p 13155:13155 synth-loop:latest
```

起服务后验证：

```bash
curl -s http://localhost:13155/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"deepseek-v4-flash","messages":[{"role":"user","content":"你好"}]}'
```

**效果信号**：`curl` 返回含 `choices[0].message.content` 的正常 JSON 响应。简单问候走规则匹配直答路径，未触发策略查询。

### 🔵 完整通道（10 分钟）

```bash
# 1. 确认策略层可用（可选）
curl http://localhost:13156/health

# 2. 体验策略注入——自动匹配专家人设
curl http://localhost:13155/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"deepseek-v4-flash","messages":[{"role":"user","content":"帮我写一份智能家居项目的商业计划书"}]}'

# 3. 体验任务链——复杂任务自动拆解
curl http://localhost:13155/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"deepseek-v4-flash","messages":[{"role":"user","content":"先分析这个项目的认证模块安全性，然后生成改进方案"}]}'

# 4. 体验相位推理——结构分形（复杂任务，用 <tc-phase> 标签触发）
curl http://localhost:13155/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"deepseek-v4-flash","messages":[{"role":"user","content":"<tc-phase>帮我完成一份市场调研报告</tc-phase>"}]}'
# → 标签显式锁定相位（structural），返回 synth_pipeline（awaiting_plan_confirm），回传 {id, action:"confirm"} 逐相位推进

# 5. 体验相位推理——链式分形（中等任务，用 <tc-phase-chain> 标签触发）
curl http://localhost:13155/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"deepseek-v4-flash","messages":[{"role":"user","content":"<tc-phase-chain>处理这个中等复杂度任务</tc-phase-chain>"}]}'
# → 标签显式锁定相位（chain）：根相位分形出多相位，子相位直接出 path（钳制深度），适合中等任务
```

### 🟣 推荐入口

把代码中 `openai.OpenAI(base_url="https://api.openai.com/v1")` 替换为 `openai.OpenAI(base_url="http://localhost:13155/v1")`。其他什么都不用改。

---


## 你获得什么能力

| 结果 | 为什么 |
|------|--------|
| **按复杂度自动分流** | 简单问题不消耗策略匹配，走规则匹配直答通道 |
| **装 100 个工具 token 不涨** | 不注册上千个工具，只注册少量内置工具 + 2 个元工具 + 按需注入动态工具 |
| **不用手写 Prompt** | 策略层自动匹配专家人设 + skills 技能分片 |
| **复杂任务一键完成** | "先分析再报告"——只需一个请求，系统自动拆解为任务链逐步执行 |
| **双生态无缝切换** | 一个入口同时兼容 OpenAI 和 Anthropic 协议 |
| **全链路可视化** | 内置管理面板：会话监控、任务链进度、管道相位进度 |
| **多相位推理** | 复杂任务拆为分形相位树自动推进——路径确认/审批/质量闸控制审查深度，只回退当前相位 |
| **统一闸** | gate_manager 跨内核编排 ck 推理闸 + pk 人闸 + 元闸，所有 chat 上下文可被闸优化（开闸时 park，可 peek/amend） |
| **LLM 层（多场景透传）** | llm_routing 多场景配置唯一真源（planning/summarize/chat/... 任意 service 透传）+ 模型级降级（503 切同池/502 切端点） |
| **统一权限** | 权限（token）+ 身份（user-id）双轨，先验权再归身份；运行时表管理 API admin scope |
| **永久区通道** | `/v1/longdata` 引入 doc/memory 到指定会话永久区（`loaded_docs` / `permanent_system_prompt`），长期存在、可删除/列出——与临时区 packets 对称 |
| **类型准入配置化** | packets 类型准入从代码写死改为 `config.yaml packets.types`，新增载荷类型改配置即可（空配置回落内置默认） |
| **相位产物落 SQLite** | pk 相位产物经 `SlArtifactStore` 桥接落 SQLite `artifacts` 表，不再只进内存——`/v1/artifacts` 可对外取，跨相位上下文回链可靠 |
---


## 媒介轴

> 🎯 每个入口都可独立使用

| 轴 | 它赋予的能力 | 一个你立刻能想象的场景 |
|----|------------|---------------------|
| **OpenAI 协议** | 任何兼容 OpenAI SDK 的应用，改 `base_url` 即获得编排能力 | 你的 GPT 应用指向 synth-loop 后，简单问候自动走规则匹配直答，复杂请求自动策略注入 |
| **Anthropic 协议** | 任何兼容 Anthropic SDK 的应用，改 `base_url` 即获得编排能力 | Claude SDK 代码指向 synth-loop 后，自动获得与 OpenAI 入口相同的编排增强 |
| **数据面协议** | `POST /v1/packets` 提交临时上下文，`packets:[id]` 引用；`/v1/longdata` 引入永久 doc/memory（v0.1.2_c） | 浏览器插件抓取页面 DOM → 提交为 packet → 对话中 LLM 自动感知页面结构；把常用资料作为 doc 引入永久区长期可用 |
| **管理面板** | 全链路可视化，不需要 grep 日志 | 任务链走到哪一步了？打开 `localhost:13155/admin/tasks` 一目了然 |

---

## 多种接入模式

| 模式 | 描述 | 适用场景 |
|------|------|---------|
| **普通模式** | 请求 → synth-loop 分类 + 路由 → 下游 LLM | 个人开发、快速体验 |
| **增强模式** | 请求 → synth-loop → 策略注入 → 下游 LLM | 生产使用，需专家 Prompt + 技能分片 |
| **完整模式** | 请求 → synth-loop → 策略注入 + 工具调度 → 下游 LLM | 复杂任务链，需跨服务工具调用 |
| **相位模式** | 标签显式锁定（`<tc-phase>` structural / `<tc-phase-chain>` chain）→ pk 分形相位树推进（规划→路径确认→执行→摘要，经推理缝收敛唯一落点） | 多步骤创作/开发/设计流程，需人工审查节点；执行经推理缝 LLM（非 text-cli） |
| **统一闸模式** | gate_manager 编排 ck/pk 闸，经 `/gate-manager/config` 切换组合；开闸时上下文 park 可 peek/amend | 需要上下文可干预/优化的应用，为未来自动化优化留可能 |

---




## 它不是什么：边界与诚实

**synth-loop 不是：**
- **不是匹配引擎**：策略匹配由外部 strata-match 负责，sl 只消费它的输出。
- **不是透传网关**：不做请求透传，每个请求都经历整套编排决策。
- **不是 LLM 框架**：不封装 LLM 调用——推理经推理缝收敛到唯一推理落点后交给下游 LLM。
- **不是策略持有者**：不持有策略，策略资产由外部策略服务管理。
- **不是指令执行者**：不执行指令，执行在 text-cli 运行时。

**诚实标注：**
- 相位编排当前固定以**中文推理资源**推进（`handle(..., lang="zh")` 单语硬编码）——这是**内部行为**，与输入问题使用的语言无关（输入可为任意语言）。
- Anthropic 下游 SSE（OpenAI 上游 → Anthropic 下游）计划在后续版本支持。

>'相位编排当前单语硬编码'是LLM获取的是中文的推理资源进行推理,是内部行为,与输入问题使用的语言无关.完全稳定后会开放多语言版本.
---

## 信任与安全边界

**不假设内网**：默认 `auth.enabled=true`（开启用户 ID 校验）；`required=false` 时"有则校验、无则放行"，`required=true` 时强制校验（未携带有效 user-id 返回 401）。

- **token 双轨**：`x-synthloop-token`（user/service/admin scope，sha256 hash 校验，先验权）+ `x-synthloop-user-id`（身份，后归身份）。
- **admin scope**：运行时表管理 API `/api/v1/runtime-endpoints` 要求 admin scope，普通 token → 403。
- **下游 LLM key**：配置在 `config.yaml` 的 `downstream_llm.api_key`，建议用 `${ENV_VAR}` 环境变量注入，不硬编码进 repo。
- **tc 令牌**：运行时表 token 加密落库（`SELF_TOKEN_ENC_KEY`）+ 管理 API 脱敏返回。

---

## 许可证

**Apache 2.0** · [LICENSE](LICENSE) · [GitHub](https://github.com/weihai-limh/synth-loop)

