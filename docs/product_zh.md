# synth-loop 产品文档

> **文档类型**：产品设计
> **版本**：v0.1.2_a | **日期**：2026-08-14
> **适用范围**：synth-loop
> **关联文档**：`design_zh.md`、`api_zh.md`
>
> synth-loop 是一个 LLM 编排引擎。对外暴露 OpenAI/Anthropic 兼容端点，内部对每次请求做分类、路由、策略注入、任务拆解。v0.1.2 新增多相位管道编排——PipelineSession 管理从想法到落地的全部状态；v0.1.2_a 将相位对外契约重铸为 **chat 多轮**（`synth_pipeline` 字段驱动），并收敛 tc 消费链路（运行时表 + 强化客户端）。

---

## 一、你被什么困扰

| 痛点 | 你的感受 |
|------|---------|
| **路径没有选择** | "你好"和"重构整个项目"走一样的流程，花一样的钱——这不合理 |
| **Prompt 靠手写** | 用户说"写商业计划书"，你得自己写专家 Prompt，每次都要从头来 |
| **复杂任务要手动拆** | "先分析代码再出报告"——你得手动分两次调 API，自己拼接结果 |
| **协议锁死** | 用了 OpenAI 的 SDK，想切 Anthropic？改代码。反之亦然 |

**核心矛盾**："你好"和"重构整个项目"走同一条路径，花同样的资源。请求复杂度差距巨大，但通用方案不分流。

---

## 二、synth-loop 解决什么问题

synth-loop 是一个编排引擎。它不对请求做透传转发——它在每次请求中做四件事：

1. **分类**：判断请求复杂度。简单问候走直接通道，复杂任务走全量增强
2. **路由**：根据复杂度选择执行路径（直答 / 策略注入 / 工具调用 / 任务链拆解）
3. **注入**：从策略层拉取匹配的专家 Prompt、技能分片、工具定义，组装上下文
4. **执行**：简单请求直接推理，复杂请求拆成任务链逐步推进
5. **管道编排**（v0.1.2）：管理多相位管道生命周期——计划编译 → 逐相位推进 → 三闸审查 → 异步委托 text-cli 执行长任务

技术组件（`src/app/services/`）：

| 组件 | 代码 | 职责 |
|------|------|------|
| 复杂度分类 | `complexity_classifier.py` | 规则 + LLM 双层判定 |
| 执行路由 | `execution_router.py` | 分形决策 + 模型选择（v0.1.2_a：6 场景 + 模型级降级） |
| 任务链执行器 | `task_chain_executor.py` | plan → execute → verify → summarize |
| 上下文注入 | `context_injector.py` | XML 标签体系上下文组装 |
| 协议翻译 | `protocol_translator.py` | Anthropic ↔ OpenAI 格式互转 |
| 降级管理器 | `degradation_manager.py` | 三层降级逻辑 |
| 运行时表 + 强化客户端（v0.1.2_a） | `runtime_endpoints.py` + `textcli_enhanced_client.py` | tc 消费收敛：alias 路由 / rank 降级 / 信封直读 |
| 相位编排器（v0.1.2_a） | `phase_chat_orchestrator.py` | chat 多轮驱动相位：synth_pipeline 状态机 + 决策点 |

---

## 三、三步开始用

### 🟢 快速通道（2 分钟）

```bash
pip install -r requirements.txt
PYTHONPATH=src python -m app.main

# 验证
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
```

### 🟣 推荐入口

把代码中 `openai.OpenAI(base_url="https://api.openai.com/v1")` 替换为 `openai.OpenAI(base_url="http://localhost:13155/v1")`。其他什么都不用改。

---

## 三.五、你刚才获得了什么

你发了一个请求，synth-loop 在内部做了分类、路由、上下文组装和推理——最终返回了一个正常的聊天补全响应。请求"你好"级别的内容自动走简单路径，不需要你手动判断走哪条通道。

你可以打开 `http://localhost:13155/admin/sessions` 看到刚才那轮对话的编排痕迹——包括复杂度判定结果、路由路径和注入的策略信息。

---

## 四、你获得什么能力

| 结果 | 为什么 |
|------|--------|
| **按复杂度自动分流** | 简单问题不消耗策略匹配，走规则匹配直答通道 |
| **多相位管道编排（v0.1.2）** | 复杂任务拆为相位序列自动推进——三闸控制审查深度，异步委托长任务 |
| **相位 chat 契约（v0.1.2_a）** | 相位 = chat 多轮：`synth_pipeline` 字段回传驱动（confirm/regenerate/abort/check_result），无需 9 端点 API——普通请求永不自动进相位（保守阈值） |
| **tc 消费收敛（v0.1.2_a）** | 三套自建 tc 调用收敛为运行时表 + 强化客户端：alias 精确路由、同 alias rank 降级、鉴权失败不降级、长任务 check_result 轮询 |
| **LLM 层升级（v0.1.2_a）** | 6 场景路由（planning 强模型/summarize 便宜模型）+ 模型级降级（503 切同池/502 切端点） |
| **统一 token（v0.1.2_a）** | 权限（token）+ 身份（user-id）双轨，先验权再归身份；运行时表管理 API admin scope |
| **装 100 个工具 token 不涨** | 不注册上千个工具，只注册少量内置工具 + 2 个元工具 + 按需注入动态工具 |
| **不用手写 Prompt** | 策略层自动匹配专家人设 + skills 技能分片 |
| **复杂任务一键完成** | "先分析再报告"——只需一个请求，系统自动拆解为任务链逐步执行 |
| **双生态无缝切换** | 一个入口同时兼容 OpenAI 和 Anthropic 协议 |
| **全链路可视化** | 内置管理面板：会话监控、任务链进度、管道相位进度 |

---

## 五、与同类方案的对比

### 与传统 Agent 框架

| 能力 | LangChain | CrewAI | AutoGen | **synth-loop** |
|------|:---------:|:------:|:-------:|:--------------:|
| 集成方式 | 嵌入式库 | 嵌入式库 | 嵌入式库 | **协议兼容（改 base_url 即用）** |
| 智能 Prompt 匹配 | ❌ | ❌ | ❌ | ✅ |
| 动态工具注入 | ❌ | ❌ | ❌ | ✅ |
| 分形决策 | ❌ | ❌ | ❌ | ✅ |
| 任务链拆解 + 推进 | 部分 | ✅ | 部分 | ✅ |
| SSE 双协议流式 | ❌ | ❌ | ❌ | ✅ |
| 三级降级 | ❌ | ❌ | ❌ | ✅ |

### 与 LLM Gateway

| 维度 | LiteLLM | Portkey | **synth-loop** |
|------|:-------:|:-------:|:--------------:|
| 核心定位 | 提供商抽象 | 企业治理 | **编排引擎** |
| 覆盖方式 | 逐个适配 SDK | 逐个适配 SDK | **协议级兼容（2 个协议）** |
| 智能 Prompt | ❌ | ❌ | ✅ |
| 动态工具注入 | ❌ | ❌ | ✅ |
| 分形路由 | ❌ | ❌ | ✅ |
| 任务链推进 | ❌ | ❌ | ✅ |

> **核心差异**：LiteLLM/Portkey 解决"如何调用 LLM"。synth-loop 解决"每个调用怎么决策路径 + 怎么注入上下文 + 怎么拆解执行"。两个赛道可以并存。

---

## 六、3 条媒介轴

> 🎯 每个入口都可独立使用

| 轴 | 它赋予的能力 | 一个你立刻能想象的场景 |
|----|------------|---------------------|
| **OpenAI 协议** | 任何兼容 OpenAI SDK 的应用，改 `base_url` 即获得编排能力 | 你的 GPT 应用指向 synth-loop 后，简单问候自动走规则匹配直答，复杂请求自动策略注入 |
| **Anthropic 协议** | 任何兼容 Anthropic SDK 的应用，改 `base_url` 即获得编排能力 | Claude SDK 代码指向 synth-loop 后，自动获得与 OpenAI 入口相同的编排增强 |
| **数据面协议** | `POST /v1/packets` 提交上下文，`packets:[id]` 引用 | 浏览器插件抓取页面 DOM → 提交为 packet → 对话中 LLM 自动感知页面结构 |
| **管理面板** | 全链路可视化，不需要 grep 日志 | 任务链走到哪一步了？打开 `localhost:13155/admin/tasks` 一目了然 |

---

## 七、三种接入模式

| 模式 | 描述 | 适用场景 |
|------|------|---------|
| **普通模式** | 请求 → synth-loop 分类 + 路由 → 下游 LLM | 个人开发、快速体验 |
| **增强模式** | 请求 → synth-loop → 策略注入 → 下游 LLM | 生产使用，需专家 Prompt + 技能分片 |
| **完整模式** | 请求 → synth-loop → 策略注入 + 工具调度 → 下游 LLM | 复杂任务链，需跨服务工具调用 |
| **管道模式（v0.1.2）** | 创建 PipelineSession → 计划编译 → 逐相位推进 → 三闸审查 → 异步委托 text-cli | 多步骤创作/开发/设计流程，需人工审查节点 |
| **相位 chat 模式（v0.1.2_a）** | 普通 chat 请求携带 `synth_pipeline` 字段 → 相位多轮推进（规划→过闸→执行→check_result）；显式触发，不劫持普通请求 | 需要相位编排的 chat 应用，无需调用 9 端点 API |

---

## 八、预设

| 主题 | 说明 |
|------|------|
| **开箱即用** | 通过 `config.yaml` 中 `strata_match.mock=true` 开启 Mock 模式，无需外部策略服务即可体验 |
| **Mock 模式** | `strata_match_client.py` 内置基于关键词的智能 Prompt 匹配（无需外部依赖） |
| **生产模式** | 配置 `strata_match.mock=false`（默认值），启动策略服务获得完整策略注入 |

---

## 九、架构预留

以下能力计划在后续版本交付：

| 能力 | 说明 | 计划版本 |
|------|------|:---:|
| 制品收集 CDN 落地 | 管道每相位产出物经 CDN 分发 | v0.1.3 |
| 物理安全/人授权激活 | 物理操作相位的播片审批 + 安全规则 | v0.1.3 |
| 质量反馈分析 | 路由准确率可观测 + 质量闭环 | v0.2 |

---

## 十、项目愿景

> 让每一个 AI 应用都获得属于自己的编排层——不是在你代码里嵌入一个框架，而是在你代码和模型中间嵌入一条智能路径。

---

## 十一、下一步（你想做什么）

| 你是什么角色 | 建议的第一件事 |
|------------|--------------|
| **开发者** | 把 SDK 的 `base_url` 指向 `localhost:13155`，感受编排的效果 |
| **架构师** | 阅读 `design_zh.md` 了解编排架构 + 数据流 |
| **维护者** | 阅读研发流程和质量管理文档了解版本研发基线 |
| **评估者** | 阅读 `functional-design_zh.md` 特性索引了解版本路线和能力覆盖 |

---

## 许可证

| 代码目录 | 协议 | 说明 |
|----------|------|------|
| `src/app/`、`src/public/` | Apache 2.0 | 核心编排引擎，自由使用 |

---

_文档版本：v1.0｜2026-08-14｜按 templates/product_recommended.md 重构 + V0.1.2_a（相位 chat 契约 / tc 消费收敛 / LLM 层 / 统一 token）_
