# synth-loop

> **版本标记**：当前文档内容基于 `v0.1.1` 验收完成的场景进行表述。当前阶段：`0.1.1 → 0.1.2`。

**LLM 编排引擎**——分类、路由、注入、执行。一次请求，一条智能路径。

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

synth-loop 是一个 **LLM 编排引擎**。它对外暴露 OpenAI/Anthropic 兼容端点，但内部不做透传——它在每次请求中做分类、路由、策略注入和任务拆解。

```
你的应用 ──OpenAI/Anthropic──→ synth-loop（编排层）
                                  ├── 复杂度分类（规则 + LLM 双层判定）
                                  ├── 分形路由（6 级 a-f 路径选择）
                                  ├── 管道编排（v0.1.2：PipelineSession + 相位推进 + 三闸审查）
                                  ├── 策略注入（专家 Prompt + 技能 + 工具）
                                  ├── 任务链推进（拆解→执行→验证→汇总）
                                  └── SSE 流式（OpenAI + Anthropic）
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

### v0.1.2 管道编排

synth-loop 不只是单请求路由器——它是**多相位管道的大脑**（v0.1.2）。

```
用户意图 → 计划编译器 → 11 步（或自定义 N 步）相位计划
                            │
              ┌─────────────┼─────────────┐
              ▼             ▼             ▼
           相位 1         相位 2    ...  相位 N
              │             │             │
    text-cli;query      策略匹配      异步委托
    （发现工具）    （strata-match）  （--async）
              │             │             │
              闸门审查 ← 人确认/驳回/跳过
```

每个相位独立配置三个闸门：**展示门**（是否看中间产物）、**编辑门**（是否允许改执行计划）、**确认门**（是否等人审查通过再推进）。全关=提需求直出结果，全开=每步审查。

长任务通过 `--async` 异步委托给 text-cli 执行，不阻塞管道推进。人可在任何相位暂停、回退、修改后继续。

---

## 五、它能为你做什么

| 结果 | 为什么 |
|------|--------|
| **按复杂度自动分流** | 简单问候不消耗策略匹配，走规则匹配直答通道 |
| **多相位管道编排（v0.1.2）** | 复杂任务拆为相位序列自动推进——三闸控制审查深度，异步委托长任务 |
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
│   ├── public/            #   管理面板 HTML
│   ├── data/              #   运行时 DB
│   ├── config.yaml        #   服务配置
│   ├── model_config.yaml  #   模型映射配置
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
| v0.1.2 | 管道引擎（PipelineSession + 状态机 + 计划编译器 + 异步委托）Phase 1~4 ✅，Phase 5 联调中 | 🔧 开发中 |


**诚实地说**：单人项目（bus factor=1），零外部用户，所有性能数据来自内部基准测试，未经第三方评测。

---

## 十、参与

| 你想做什么 | 去这里 |
|-----------|--------|
| 快速上手 | 看上面的「三步开始用」 |
| 了解架构 | [docs/design_zh.md](docs/design_zh.md) |

---

## 四件套

每个项目都可以单独部署、单独提供价值。它们原生解耦——
只在管道场景中组合，且 synth-loop 在 strata-match / text-cli 不可用时自动降级运行。

| 项目 | 独立做什么 | 在管道中的角色 |
|------|-----------|---------------|
| [text-cli](https://github.com/weihai-limh/text-cli) | 分布式指令执行——`AI:域;动作` 协议，10 个工具包随运行时附带，A0-A9 渐进式部署 | 执行引擎——计划编译器输出 path JSON → `--async` 异步委托 |
| [strata-match](https://github.com/weihai-limh/strata-match) | 策略供应——`POST /api/v1/query` 返回 Prompt+技能+工具，相位驱动动态策略生成（v0.1.2） | 策略供应——每相位动态匹配最优 Prompt + 技能分片 |
| synth-loop | LLM 编排——OpenAI/Anthropic 兼容端点，分形路由+任务链+多相位管道（v0.1.2） | 管道大脑——PipelineSession + 计划编译器 + 三闸推进 |
| [drive-magic](https://github.com/weihai-limh/drive-magic) | 融合镜像——一条 docker 命令拉起全栈，Web 管理面+六媒介触达，Chrome 插件管道仪表盘（v0.1.1） | 管道界面——相位进度条、路径编辑器、制品预览 |

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
