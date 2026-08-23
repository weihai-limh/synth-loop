# synth-loop

> An intelligent switching hub exposed as an LLM gateway — classify, route, inject, and execute. One request, one intelligent path. / 以 LLM 网关形态暴露的智能交换中枢——分类、路由、注入、执行。一次请求，一条智能路径。

[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)

---

🌐 **中文** | English (coming in v1.0)

> 当前主语言：中文。完整文档见 [README_zh.md](README_zh.md)。
> Current primary language: Chinese. Full documentation at [README_zh.md](README_zh.md).

---

## ⚡ 30s to see it work / 30 秒看到效果

```bash
pip install -r requirements.txt
PYTHONPATH=src python -m app.main

curl -s http://localhost:13155/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"deepseek-v4-flash","messages":[{"role":"user","content":"你好"}]}'
```

**Effect signal / 效果信号**：A normal chat completion response with `choices[0].message.content`. The greeting-level input is classified by rule matching and takes the direct chat path — no strategy query triggered. / 返回含 `choices[0].message.content` 的正常 JSON 响应。问候级输入走规则匹配直答路径，未触发策略查询。

---

## What it is / 它是什么

An intelligent switching hub exposed as an LLM gateway — **externally an LLM gateway face** (OpenAI/Anthropic-compatible), **internally a smart dispatch & converge hub**: every request, it decides **which path, which context, which gate, which model, how to reason multi-step**, then converges all inference to a single inference point. Not a transparent gateway, not a plain orchestration engine.

对外是一张 LLM 网关的"脸"（OpenAI/Anthropic 兼容端点），对内是一个做智能分派与收束的交换中枢——每次请求替你做整套决策：**走哪条路径、装什么上下文、过什么闸、用哪个模型、怎么多步推理**，最终把所有这些推理**收束到唯一推理落点**。它不是透传的网关，也不是单纯的编排引擎。

---

## What it does / 核心能力

| Capability / 能力 | How / 原理 |
|------|------|
| **Fractal routing / 分形决策** | Classifies request complexity. Simple queries skip strategy matching. / 按请求复杂度选择最经济的执行路径 |
| **Context kernel / 上下文内核** | ck assembles context + gate listens every inference; all chat context optimizable / ck 统一拼装上下文 + 闸监听每次推理，所有 chat 上下文可被优化 |
| **Phase reasoning / 相位推理** | pk decomposes complex tasks into multi-phase steps with gates / pk 将复杂任务拆为多步相位 + 闸审查 |
| **Strategy injection / 策略注入** | Auto-matches expert prompts + skill shards + tool definitions per intent / 按意图自动匹配专家 Prompt + 技能分片 + 工具 |
| **Task chain execution / 任务链推进** | Decomposes "analyze then report" into plan → execute → verify → summarize / 复杂任务自动拆解为多步执行链 |
| **Unified gate / 统一闸** | gate_manager orchestrates ck/pk gates across kernel loop / gate_manager 跨内核编排 ck/pk 闸 |
| **Dual-protocol streaming / 双协议流式** | OpenAI + Anthropic SSE, one codebase / 一个入口同时兼容两套协议 |

> **Dependency / 前置依赖**：Full experience needs strata-match at `localhost:13156`. Degrades gracefully with built-in defaults. / 完整体验需要外部策略服务，可降级使用内置默认策略独立运行。

---

## Dev status / 开发状态

| Version / 版本 | Criteria / 验收标准 | Status / 状态 |
|------|---------|:----:|
| v0.1 | 112/112 static tests PASS | ✅ |
| v0.1.1 | 189 static tests PASS, 9 dynamic scripts ready | ✅ |


**Honesty / 诚实地说**：Solo project (bus factor=1), zero external users, all benchmarks are internal. / 单人项目（bus factor=1），零外部用户，所有性能数据来自内部基准测试。

---

## Navigation / 参与

| 你想做什么 | 去这里 |
|------|------|
| 📖 完整中文文档 | [README_zh.md](README_zh.md) |
| 🏗️ 架构设计 | [docs/design_zh.md](docs/design_zh.md) |
| 📡 API 参考 | [docs/api_zh.md](docs/api_zh.md) |
| 🐛 报告问题 | GitHub Issues |

---

## License / 许可证

`src/app/` & `src/public/`: Apache 2.0
