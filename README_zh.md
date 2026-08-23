# synth-loop



**以 LLM 网关形态暴露的智能交换中枢**——分类、路由、注入、执行。一次请求，一条智能路径。

[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)

---

## ⚡ 30 秒看到效果

```bash
pip install -r requirements.txt
PYTHONPATH=src python -m app.main

curl -s http://localhost:13155/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"deepseek-v4-flash","messages":[{"role":"user","content":"你好"}]}'
```

**效果信号**：返回含 `choices[0].message.content` 的正常 JSON 响应。问候级输入被规则引擎分类后走直答通道，未触发策略查询。打开 `http://localhost:13155/admin/sessions` 可以看到这轮对话的编排痕迹。

---

## 一、它是什么

synth-loop 是一个 **以 LLM 网关形态暴露的智能交换中枢**——**对外，它是一张 LLM 网关的"脸"**（OpenAI/Anthropic 兼容端点，任何 SDK 指向它即可接入）；**对内，它是一个做智能分派与收束的交换中枢**——每一次请求进来，它替你做整套决策：**走哪条路径、装什么上下文、过什么闸、用哪个模型、怎么多步推理**，最终把所有这些推理**收束到唯一推理落点**。它**不是**透传的网关（不原样转发），也**不是**单纯的编排引擎——它是各方的交汇点，把对的东西智能地分派到对的地方。

```
你的应用 ──OpenAI/Anthropic──→ synth-loop（智能交换中枢）
                                  │
                                  ├─ 消息前置检查（分形之前）
                                  │    └─ 相位意图："用相位"/"用链" → 相位推理（pk 结构/链式分形相位树）
                                  │       （不走问题分形；未命中则进入分形路由 ↓）
                                  │
                                  ├─ 复杂度分类 + 分形路由（6 级 a-f）→ 选一条路径：
                                  │    简单对话 → chat / prompt_chat（策略注入）
                                  │    复杂任务 → task_chain
                                  │
                                  ├─ 上下文内核（ck：拼装 + 闸监听）      ← 装什么上下文、过什么闸
                                  ├─ 统一闸（gate_manager：跨内核编排）   ← 过什么闸
                                  ├─ 唯一推理落点（sl_llm_provider）      ← 用哪个模型、怎么推理
                                  └─ SSE 流式（OpenAI + Anthropic）
```

> **前置依赖**：完整体验需要策略服务运行在 `localhost:13156`。synth-loop 可降级独立运行（使用内置默认策略 + 内置工具）。

---

## 二、你被什么困扰

| 痛点 | 你的感受 |
|------|---------|
| **路径没有选择** | "你好"和"重构整个项目"走一样的流程，花一样的钱 |
| **Prompt 靠手写** | 用户说"写商业计划书"，你得自己写专家 Prompt——每次都要 |
| **复杂任务要手动拆** | "先分析代码再出报告"——你得手动分两次调 API |
| **协议锁死** | 用了 OpenAI 的 SDK，想切 Anthropic？改代码 |

**核心矛盾**："你好"和"重构整个项目"走同一条路径，花同样的资源。请求复杂度差距巨大，但通用方案不分流。

---

## 三、三步开始用

### 1️⃣ 快速通道（2 分钟）

```bash
pip install -r requirements.txt
PYTHONPATH=src python -m app.main

# 验证
curl http://localhost:13155/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"deepseek-v4-flash","messages":[{"role":"user","content":"你好"}]}'
```

### 2️⃣ 体验策略注入

```bash
curl http://localhost:13155/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"deepseek-v4-flash","messages":[{"role":"user","content":"帮我写一份智能家居项目的商业计划书，包含市场分析和财务预测"}]}'
# → synth-loop 自动查询策略层，注入专家 Prompt 后推理
```

### 3️⃣ 体验任务链

```bash
curl http://localhost:13155/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"deepseek-v4-flash","messages":[{"role":"user","content":"先分析这个项目的认证模块安全性，然后生成一份改进方案报告"}]}'
# → synth-loop 自动拆解为"分析→识别问题→生成报告"三步执行
```

---

## 四、它怎么工作

```
请求 → 上游过滤 → 复杂度分类 → 分形路由 → 策略注入 → 任务链 → LLM/SSE → 响应
```

**分形路由的三层递进**：

```
层1：规则匹配（<1ms，0 token）→ 规则覆盖两端极值——"你好"走直答，"先.*再"走任务链
层2：分形 Prompt（1 次 LLM 调用）→ 6 级 a-f 路由——a/chat、b/prompt_chat、c/task、e/f/task_chain
层3：降级兜底 → 策略层不可用时走内置默认策略
```

> 架构细节详见 `docs/design_zh.md`

### v0.1.2 相位推理 + 统一闸

synth-loop 不只是单请求路由器——对复杂任务，它是**多步相位推理的大脑**（v0.1.2，_b 集成 pk 内核）。

```
复杂意图 → 相位推理（pk 内核）
              │  分形相位树：结构分形（复杂）∥ 链式分形（中等）
              ┌──────────────┬──────────────┐
              ▼              ▼              ▼
           相位 1          相位 2     ...  相位 N
              │              │              │
          规划 → 工具组成的执行路径确认 → 执行 → 摘要  （规划及摘要-经推理缝，收敛到唯一推理落点）
              │              │              │
              闸审查 ← 人确认/驳回/重试/中止（gate_manager 统一编排）
```

- **分形相位树**：复杂任务按结构分形层层展开（structural），中等任务走链式（chain）钳制子相位深度——都是"根分形 + 子 LEAF"。
- **推理缝收束**：每个相位的规划/执行/摘要都经推理缝，收敛到唯一推理落点（`sl_llm_provider`），上下文经 ck 内核拼装 + 闸监听。
- **统一闸（gate_manager）**：跨内核编排——相位路径确认/审批（pk 人闸）+ 上下文干预（ck 推理闸）+ ck 闸开关（元闸），经 `/gate-manager/config` 切换组合，供外挂服务干预。
- **人可在任何相位暂停、确认、驳回、重试、中止**，只回退当前相位（局部回退）。

> 相位执行经推理缝 LLM（不走 text-cli）——这是 _b 的整体替换语义：相位推理统一由 LLM 经推理缝完成。

---

## 五、它能为你做什么

| 结果 | 为什么 |
|------|--------|
| **按复杂度自动分流** | 简单问候不消耗策略匹配，走规则匹配直答通道 |
| **多相位推理（v0.1.2）** | 复杂任务拆为分形相位树自动推进——路径确认/审批/质量闸控制审查深度，只回退当前相位 |
| **装 100 个工具 token 不涨** | 不注册上千个工具，只注册 2 个元工具 + 按需注入动态工具 |
| **不用手写 Prompt** | 策略层自动匹配专家人设 + skills 技能分片 |
| **复杂任务一键完成** | "先分析再报告"——只需一个请求，系统自动拆解执行 |
| **双生态无缝切换** | 一个入口同时兼容 OpenAI 和 Anthropic 协议 |
| **管道全链路可视化** | 内置管理面板：相位进度、任务链步骤、会话编排痕迹 |

---

## 六、3 条媒介轴

> 🎯 每个入口都可独立使用

| 轴 | 媒介 | 它赋予的能力 | 一个你能想象的场景 |
|----|------|------------|---------------------|
| OpenAI 协议 | `base_url=http://localhost:13155/v1` | 任何 OpenAI SDK 应用改 base_url 即获得编排 | 你的 GPT 应用指向 synth-loop，自动获得分类+策略注入+流式 |
| Anthropic 协议 | `base_url=http://localhost:13155` | 任何 Anthropic SDK 应用不改代码即获得编排 | Claude 代码指向 synth-loop，获得与 OpenAI 入口相同的编排增强 |
| 管理面板 | `http://localhost:13155/admin/*` | 全链路可视化 | 打开浏览器看任务链步骤进度、编排决策路径 |

---

## 七、项目结构

```
synth-loop/
├── src/                   # 源码
│   ├── app/               #   Python 包（main / routers / services / models / tools / middleware）
│   │   ├── kernels/       #   vendored 内核组件（context_kernel / phase_kernel，纯副本热更新）
│   │   └── services/      #   sl_llm_provider / gate_manager / inference_seam / kernel_adapters 等
│   ├── public/            #   管理面板 HTML
│   ├── data/              #   运行时 DB
│   ├── config.yaml        #   服务配置
│   ├── model_config.yaml  #   模型映射配置（llm_routing 多场景 = 唯一真源）
│   └── complexity_rules.yaml # 复杂度规则
├── deploy/                
│   └── container/         #   Docker 镜像
├── docs/                  
│   ├── product_zh.md      #     产品文档
│   ├── design_zh.md       #     架构设计
│   └── api_zh.md          #     API 参考
└── examples/              # 示例
```

---

## 八、文档地图

| 类别 | 文件 | 说明 |
|------|------|------|
| 📖 产品文档 | [docs/product_zh.md](docs/product_zh.md) | 产品定位、能力、上手 |
| 🏗️ 设计文档 | [docs/design_zh.md](docs/design_zh.md) | 系统架构、数据流、配置 |
| 📡 API 参考 | [docs/api_zh.md](docs/api_zh.md) | 端点定义、编排语义 |

---

## 九、开发状态与版本模型

| 版本 | 验收标准 | 状态 |
|------|---------|:----:|
| v0.1 | 112/112 静态测试 PASS，dynamic 全部通过 | ✅ 已发布 |
| v0.1.1 | 189 静态测试 PASS，9 动态脚本就绪 | ✅ 已发布 |
| v0.1.2 | 相位推理（pk）+ 上下文内核（ck）+ 统一闸 + 三前置 + 主路径过闸 | ✅（_b 完成，104 测试通过） |

---

## 十、参与

| 你想做什么 | 去这里 |
|-----------|--------|
| 快速上手 | 看上面的「三步开始用」 |
| 了解架构 | [docs/design_zh.md](docs/design_zh.md) |

---


## 管理面板

| 面板 | 地址 |
|------|------|
| 会话监控 | http://localhost:13155/admin/sessions |
| 任务链监控 | http://localhost:13155/admin/tasks |
| Job 管理 | http://localhost:13155/admin/jobs |
| 用户管理 | http://localhost:13155/admin/users |

---

## 许可证

| 代码目录 | 协议 | 说明 |
|----------|------|------|
| `src/app/`、`src/public/` | Apache 2.0 | 核心编排引擎，自由使用 |
