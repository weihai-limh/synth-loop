# synth-loop

**A task-processing hub exposed as an LLM gateway** — classify, route, inject, and execute. One request, one intelligent path.

[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)

---

## ⚡ 30 seconds to see it work

Use the prebuilt artifacts — unpack and run (want to build yourself? see `scripts/docs/release_zh.md`):

```bash
# After unpacking on Windows
deploy/win/synth-loop-v0.1.2/start.bat

# After unpacking on Linux
bash deploy/linux/synth-loop-v0.1.2/start.sh

# Container (on a machine with Docker)
python scripts/release/container/build.py
docker run -d -p 13155:13155 synth-loop:latest
```

Verify after the service is up:

```bash
curl -s http://localhost:13155/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"deepseek-v4-flash","messages":[{"role":"user","content":"hello"}]}'
```

**Effect signal**: a normal chat completion response containing `choices[0].message.content`. Greeting-level input is classified by the rule engine and takes the direct-answer path, without triggering strategy queries. Open `http://localhost:13155/admin/sessions` to see the orchestration trace of this exchange.

---

## What it is

synth-loop is a **task-processing hub exposed as an LLM gateway** — **externally, it wears the "face" of an LLM gateway** (OpenAI/Anthropic-compatible endpoints; any SDK pointed at it just works); **internally, it is a switching hub that dispatches and converges** — for every request, it makes the whole set of decisions for you: **which path, which context, which gate, which model, how to reason multi-step**, finally converging all of that inference to a **single inference point**. It is **not** a transparent gateway (it does not forward verbatim), and it is **not** a plain orchestration engine — it is the junction where the right things get dispatched to the right places.

```
Your app ──OpenAI/Anthropic──→ synth-loop (task-processing hub)
                                  │
                                  ├─ Pre-dispatch message checks
                                  │    └─ Phase tags: <tc-phase>target</tc-phase> / <tc-phase-chain>target</tc-phase-chain>
                                  │       → phase reasoning (pk structural/chain fractal phase tree; not problem fractal; no tag → fractal routing ↓)
                                  │
                                  ├─ Complexity classification + fractal routing (6 levels a-f) → pick one path:
                                  │    simple chat → chat / prompt_chat (strategy injection)
                                  │    tasks not needing phase reasoning → task_chain
                                  │
                                  ├─ Context kernel (ck: assembly + gate listening)   ← which context, which gate
                                  ├─ Unified gate (gate_manager: cross-kernel)        ← which gate
                                  ├─ Single inference point (sl_llm_provider)         ← which model, how to reason
                                  └─ SSE streaming (OpenAI + Anthropic)
```

> **Prerequisite**: the full experience needs the strategy service running at `localhost:13156`. synth-loop degrades and runs standalone (built-in default strategy + tool query).

**What it is / is not**:

| Is | Is not |
|------|------|
| Task-processing hub — dispatch + converge (single inference point `sl_llm_provider`) | Matching engine (strategy matching is handled by the external strata-match) |
| Protocol-compatible endpoint — OpenAI + Anthropic dual-protocol entry | API proxy / neutral gateway — no request passthrough; every request goes through orchestration decisions |
| Context-kernel host — ck six-layer assembly + gate listening | LLM framework (does not wrap LLM calls) |
| Task handler — fractal routing, phase reasoning (pk), unified gate, unified data plane | Strategy owner (strategy is managed by the external strategy service) |

---

## Get started in 3 steps

### 1️⃣ Quick start (2 minutes)

```bash
# After unpacking on Windows
deploy/win/synth-loop-v0.1.2/start.bat

# After unpacking on Linux
bash deploy/linux/synth-loop-v0.1.2/start.sh

# Container (on a machine with Docker)
python scripts/release/container/build.py
docker run -d -p 13155:13155 synth-loop:latest
```

Verify after the service is up:

```bash
curl http://localhost:13155/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"deepseek-v4-flash","messages":[{"role":"user","content":"hello"}]}'
```

### 2️⃣ Experience strategy injection

```bash
curl http://localhost:13155/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"deepseek-v4-flash","messages":[{"role":"user","content":"Write a business plan for a smart-home project, including market analysis and financial forecasts"}]}'
# → synth-loop queries the strategy layer, injects the expert prompt, then reasons
```

### 3️⃣ Experience task chain

```bash
curl http://localhost:13155/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"deepseek-v4-flash","messages":[{"role":"user","content":"First analyze the security of this project's authentication module, then generate an improvement report"}]}'
# → synth-loop decomposes it into "analyze → identify issues → generate report" and executes step by step
```

---

## How it works

```
Request → upstream filtering → complexity classification → fractal routing → strategy injection → task chain → LLM/SSE → response
```

**Three tiers of fractal routing**:

```
Tier 1: rule matching (<1ms, 0 token) → rules cover only the two extremes — "hello" goes direct-answer, "first.*then" goes task chain
Tier 2: fractal prompt (1 LLM call) → 6-level a-f routing — a/chat, b/prompt_chat, c/task, e/f/task_chain
Tier 3: degradation fallback → built-in default strategy when the strategy layer is unavailable
```

> Architecture details: see `docs/design_zh.md`

### Phase reasoning + unified gate

synth-loop is not just a single-request router — for complex tasks it solves them through **multi-step phase reasoning** (integrating text-cli's pk(phase_kernel) kernel).

```
Complex intent → phase reasoning (pk kernel)
              │  Fractal phase tree: structural (complex) ∥ chain (medium)
              ┌──────────────┬──────────────┐
              ▼              ▼              ▼
           Phase 1         Phase 2    ...   Phase N
              │              │              │
          plan → tool-composed path confirm → execute → summarize  (plan & summarize go through the inference seam, converging on the single inference point)
              │              │              │
              gate review ← human confirm/reject/retry/abort (gate_manager unified orchestration)
```

- **Fractal phase tree**: complex tasks expand layer by layer via structural fractal; medium tasks use chain (clamping sub-phase depth) — both are "root fractal + child LEAF".
- **Inference-seam convergence**: every phase's plan/execute/summarize go through the inference seam, converging on the single inference point (`sl_llm_provider`), with context assembled by the ck kernel + gate listening.
- **Unified gate (gate_manager)**: cross-kernel orchestration — phase path confirm/approve (pk human gate) + context intervention (ck reasoning gate) + ck gate switch (meta gate), combo switched via `/gate-manager/config`, open to external-service intervention.
- **A human can pause, confirm, reject, retry, abort at any phase**, only rolling back the current phase (local rollback).

---

## What it can do for you

| Result | Why |
|------|--------|
| **Auto-routing by complexity** | Simple greetings skip strategy matching and take the rule-matched direct-answer path |
| **Multi-phase reasoning** | Complex tasks decompose into a fractal phase tree that advances automatically — path confirm/approve/quality gates control review depth, only the current phase rolls back |
| **Dual-channel data plane** | Temporary channel `packets` (environment context, type allow-list configurable) + permanent channel `/v1/longdata` (long-lived doc/memory) |
| **100 tools without token growth** | Registers no thousands of tools — only 2 meta tools + on-demand dynamic tool injection |
| **No hand-written prompts** | The strategy layer auto-matches expert personas + skills fragments |
| **One request for complex tasks** | "Analyze then report" — one request, auto-decomposed and executed |
| **Seamless dual-ecosystem switch** | One entry, compatible with both OpenAI and Anthropic protocols |
| **Full-pipeline visualization** | Built-in admin panels: phase progress, task-chain steps, session orchestration traces |

---

## Project structure

```
synth-loop/
├── src/
│   ├── sl-py/                       # ★ synth-loop's Python implementation
│   │   ├── app/                     #   Python package (main / routers / services / models / tools / middleware)
│   │   │   ├── kernels/             #   vendored copies (sl's folder-level integration point for ck/pk)
│   │   │   │   ├── context_kernel/  #   ← vendored copy of ck
│   │   │   │   └── phase_kernel/    #   ← vendored copy of pk
│   │   │   └── services/            #   sl_llm_provider / gate_manager / inference_seam / kernel_adapters / longdata / sl_artifact_store etc.
│   │   ├── public/                  #   admin panel HTML
│   │   ├── data/                    #   runtime DB
│   │   ├── config.yaml              #   service config
│   │   ├── model_config.yaml        #   model mapping config (llm_routing multi-scenario = single source of truth)
│   │   └── complexity_rules.yaml    #   complexity rules
│   ├── sl-web-chat/                 # ★ sidecar Web shell (single-file html, double-click to open, connects to this backend)
│   │   ├── sl-web-chat.html         #   default bilingual artifact (sole distributable, double-click to open)
│   │   ├── sl-web-chat-src/         #   source (in version control, not in artifacts): build.js self-service packaging for other languages
│   │   └── README_zh.md             #   web-shell's own docs (capabilities / integration / source-artifact discipline)
│   └── ck-py/                       # ★ context_kernel's Python implementation
│       ├── context_kernel/          #   ck core source (adapters / core / ports / serve)
│       │   └── serve/               #   core sidecar service (server.py + session_store.py) -- deployable standalone, ck's "standalone consumption surface"
│       └── docs/                    #   ck's own docs (design / user-manual)
├── deploy/
│   └── container/                   #   Docker image
├── docs/en/
│   ├── product_en.md                #     product doc
│   └── design_en.md                 #     architecture design
└── examples/                        #   examples
```

> **Kernel integration note**: synth-loop itself is `sl-py`. It integrates two kernels as folders — **ck (context_kernel)** and **pk (phase_kernel)** — via **folder-level vendored integration** (a copy is kept under `sl-py/app/kernels/` and imported from that copy).

---

## Document map

> Chinese is authoritative; English is derived from the Chinese docs. Product/design English docs are derived and maintained by AI; the API reference currently lives in Chinese (`api_zh.md`), with the English version to be derived.

| You are | Go here |
|:---|:---|
| Full English | [online](https://github.com/weihai-limh/synth-loop/blob/main/docs/en/README_en.md) or [relative](docs/en/README_en.md) |
| Product doc | [online](https://github.com/weihai-limh/synth-loop/blob/main/docs/en/product_en.md) or [relative](docs/en/product_en.md) |
| Architecture & implementation details | [online](https://github.com/weihai-limh/synth-loop/blob/main/docs/en/design_en.md) or [relative](docs/en/design_en.md) |
| API reference | [online](https://github.com/weihai-limh/synth-loop/blob/main/docs/api_zh.md) or [relative](docs/api_zh.md) |

---

## Development status & versioning

| Version | Acceptance criteria | Status |
|------|---------|:----:|
| v0.1 | 112/112 static tests PASS, dynamic all passed | ✅ Released |
| v0.1.1 | 189 static tests PASS, 9 dynamic scripts ready | ✅ Released |
| v0.1.2 | phase reasoning (pk) + context kernel (ck) + unified gate + three pre-checks + main path through gate | ✅ (130 tests pass) |
| v0.1.2_a | tc consumption pipeline converged (runtime-endpoints + enhanced client + unified token + artifact data plane) | ✅ Reinforcement (no version bump) |
| v0.1.2_b | unified-gate config surface (`/gate-manager/config`) + llm_routing multi-scenario single source of truth | ✅ Reinforcement (no version bump) |
| v0.1.2_c | dual-channel data plane (packets type allow-list config + longdata permanent channel) + artifacts relaxed | ✅ Reinforcement (no version bump) |
| v0.1.2_d | logic_category externalized + TaskChainService single-step loop (old TaskChainExecutor removed) | ✅ Reinforcement (no version bump) |
| v0.1.2_e | pk kernel integration (sm seam + i18n single-locale + PhasePlanPlanner wired to sm + _PkGateAdapter real gates) | ✅ Reinforcement (no version bump) |

---

## License

**Apache 2.0** · [LICENSE](LICENSE) · [GitHub](https://github.com/weihai-limh/synth-loop)
