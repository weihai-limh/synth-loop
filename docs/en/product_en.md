# synth-loop Product Documentation

> **Doc type**: Product design
> **Version**: v0.1.2_e | **Date**: 2026-08-26
> **Scope**: synth-loop
> **Related docs**: `design_zh.md`, `api_zh.md`
>
> synth-loop is a **task-processing hub exposed as an LLM gateway**. Externally it exposes OpenAI/Anthropic-compatible endpoints; internally it makes the full set of decisions for every request (which path, which context, which gate, which model, how to reason multi-step), converging on a single inference point.

---

## What problems synth-loop solves

1. **Classify**: judge request complexity. Simple greetings take the direct channel, complex tasks get full enhancement.
2. **Route**: pick one execution path by complexity (direct answer / strategy injection / tool call / task chain / phase reasoning).
3. **Inject**: pull matching expert prompts, skills fragments, and tool definitions from the strategy layer to assemble context.
4. **Execute**: simple requests reason directly; complex requests decompose into task chains or phases and advance step by step, converging via the inference seam to the single inference point.
5. **Phase reasoning**: decompose complex tasks into a fractal phase tree — structural (complex) / chain (medium), plan → path confirm → execute → summarize, every phase gate-reviewable.
6. **Unified gate**: gate_manager cross-kernel orchestration — phase path confirm/approve (pk human gate) + context intervention (ck reasoning gate) + gate switch (meta gate); all chat contexts can be gate-optimized.

Technical components (`src/sl-py/app/services/` + `src/sl-py/app/kernels/`):

| Component | Code | Responsibility |
|------|------|------|
| Complexity classification | `complexity_classifier.py` | rule + LLM two-tier judgment |
| Single inference point | `sl_llm_provider.py` | all paths converge; generic service selection + ck gate integration |
| Execution routing | `execution_router.py` | fractal decision + model selection (multi-scenario passthrough, llm_routing config = single source of truth) |
| Context kernel | `kernels/context_kernel/` (vendored) | six-layer assembly + reasoning gate + gate_mode |
| Phase kernel | `kernels/phase_kernel/` (vendored) | fractal phase tree + three gates + checkpoint + inference seam + sm seam (SmStrategyBundle structured policy) + i18n (`i18n/*.json`, sl single-locale default zh) |
| Inference seam | `inference_seam.py` | SlInferenceSeam: pk inference seam, exposed to build_messages, assembled by ck + gate |
| Unified gate | `gate_manager.py` | cross-kernel gate orchestration: five GateTypes + combo functions + cross-kernel loop |
| Task chain service | `task_chain_service.py` (new in v0.1.2_d, replaces deleted `task_chain_executor.py` #6 red line) | single-step loop: write tasks table (queued) → delegate text-cli `--async` → poll → confirm gate (internal `_dispatch_confirm`) → write back (completed/error); inherits G3 persistence responsibility |
| Context injection | `context_injector.py` | task-chain step context injection (completed steps + current step) |
| Protocol translation | `protocol_translator.py` | Anthropic ↔ OpenAI format conversion |
| Degradation manager | `degradation_manager.py` | three-tier degradation logic |
| Phase orchestrator | `phase_chat_orchestrator.py` | chat multi-turn contract (_e: planner wired to sm=PhasePlanPlanner, url from `config.strata_match.url`; `handle(..., lang="zh")` single-locale hardcoded) |

---

## Get started in 3 steps

### 🟢 Quick start (2 minutes)

Use the artifacts — unpack and run (artifact build: see `scripts/docs/release_zh.md`):

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

**Effect signal**: `curl` returns a normal JSON response with `choices[0].message.content`. Greeting-level input takes the rule-matched direct-answer path, without triggering strategy queries.

### 🔵 Full walkthrough (10 minutes)

```bash
# 1. Confirm the strategy layer is available (optional)
curl http://localhost:13156/health

# 2. Experience strategy injection — auto-matching expert persona
curl http://localhost:13155/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"deepseek-v4-flash","messages":[{"role":"user","content":"Write a business plan for a smart-home project"}]}'

# 3. Experience task chain — complex task auto-decomposition
curl http://localhost:13155/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"deepseek-v4-flash","messages":[{"role":"user","content":"First analyze the security of this project's authentication module, then generate an improvement plan"}]}'

# 4. Experience phase reasoning — structural fractal (complex task, triggered with the <tc-phase> tag)
curl http://localhost:13155/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"deepseek-v4-flash","messages":[{"role":"user","content":"<tc-phase>Complete a market research report for me</tc-phase>"}]}'
# → tag explicitly locks the phase (structural); returns synth_pipeline (awaiting_plan_confirm); pass back {id, action:"confirm"} to advance phase by phase

# 5. Experience phase reasoning — chain fractal (medium task, triggered with the <tc-phase-chain> tag)
curl http://localhost:13155/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"deepseek-v4-flash","messages":[{"role":"user","content":"<tc-phase-chain>Process this medium-complexity task</tc-phase-chain>"}]}'
# → tag explicitly locks the phase (chain): the root fractal produces multiple phases, child phases go straight to path (depth clamped), suited to medium tasks
```

### 🟣 Recommended entry

Replace `openai.OpenAI(base_url="https://api.openai.com/v1")` in your code with `openai.OpenAI(base_url="http://localhost:13155/v1")`. Nothing else changes.

---

## What capabilities you get

| Result | Why |
|------|--------|
| **Auto-routing by complexity** | Simple problems skip strategy matching and take the rule-matched direct-answer path |
| **100 tools without token growth** | Registers no thousands of tools — a few built-in tools + 2 meta tools + on-demand dynamic tool injection |
| **No hand-written prompts** | The strategy layer auto-matches expert personas + skills fragments |
| **One request for complex tasks** | "Analyze then report" — one request, auto-decomposed into a task chain and executed step by step |
| **Seamless dual-ecosystem switch** | One entry, compatible with both OpenAI and Anthropic protocols |
| **Full-pipeline visualization** | Built-in admin panels: session monitoring, task-chain progress, pipeline phase progress |
| **Multi-phase reasoning** | Complex tasks decompose into a fractal phase tree that advances automatically — path confirm/approve/quality gates control review depth, only the current phase rolls back |
| **Unified gate** | gate_manager cross-kernel orchestration of ck reasoning gate + pk human gate + meta gate; all chat contexts can be gate-optimized (park when open, peek/amend) |
| **LLM layer (multi-scenario passthrough)** | llm_routing multi-scenario config = single source of truth (planning/summarize/chat/... any service passthrough) + model-level degradation (503 switch same-pool / 502 switch endpoint) |
| **Unified permission** | permission (token) + identity (user-id) dual track, verify permission then attribute identity; runtime-endpoint management API requires admin scope |
| **Permanent channel** | `/v1/longdata` introduces doc/memory into a session's permanent zone (`loaded_docs` / `permanent_system_prompt`), long-lived, deletable/listable — symmetric with the temporary packets channel |
| **Type allow-list configurable** | packets type allow-list moved from hardcoded to `config.yaml packets.types`; adding a payload type is config-only (empty config falls back to the built-in default) |
| **Phase artifacts to SQLite** | pk phase artifacts bridge via `SlArtifactStore` into the SQLite `artifacts` table, no longer memory-only — `/v1/artifacts` fetchable externally, reliable cross-phase context chaining |

---

## Media axes

> 🎯 Each entry works independently

| Axis | What it gives | A scene you can picture immediately |
|----|------------|---------------------|
| **OpenAI protocol** | Any OpenAI-SDK-compatible app gains orchestration by changing `base_url` | After your GPT app points to synth-loop, simple greetings auto-route to rule-matched direct answers, complex requests auto-inject strategy |
| **Anthropic protocol** | Any Anthropic-SDK-compatible app gains orchestration by changing `base_url` | After your Claude SDK points to synth-loop, it gets the same orchestration enhancement as the OpenAI entry |
| **Data-plane protocol** | `POST /v1/packets` submits temporary context referenced by `packets:[id]`; `/v1/longdata` introduces permanent doc/memory (v0.1.2_c) | A browser extension grabs page DOM → submits as packet → the LLM auto-perceives page structure in dialogue; introduce common material as doc into the permanent zone for long-term use |
| **Admin panel** | Full-pipeline visualization, no grep needed | Where is the task chain now? Open `localhost:13155/admin/tasks` and see at a glance |

---

## Multiple access modes

| Mode | Description | Use case |
|------|------|---------|
| **Normal** | request → synth-loop classify + route → downstream LLM | personal development, quick experience |
| **Enhanced** | request → synth-loop → strategy injection → downstream LLM | production use, needs expert prompt + skills fragments |
| **Full** | request → synth-loop → strategy injection + tool dispatch → downstream LLM | complex task chains needing cross-service tool calls |
| **Phase** | tag explicitly locks (`<tc-phase>` structural / `<tc-phase-chain>` chain) → pk fractal phase tree advances (plan → path confirm → execute → summarize, converging via the inference seam to the single point) | multi-step creative/development/design flows needing human review nodes; execution goes through the inference-seam LLM (not text-cli) |
| **Unified gate** | gate_manager orchestrates ck/pk gates, combo switched via `/gate-manager/config`; context parks for peek/amend when the gate is open | apps needing context intervention/optimization; leaves room for future automated optimization |

---

## What it is not: boundaries and honesty

**synth-loop is not:**
- **Not a matching engine**: strategy matching is handled by the external strata-match; sl only consumes its output.
- **Not a transparent gateway**: no request passthrough; every request goes through the full orchestration decisions.
- **Not an LLM framework**: does not wrap LLM calls — inference converges via the inference seam to the single inference point, then goes to the downstream LLM.
- **Not a strategy owner**: holds no strategy; strategy assets are managed by the external strategy service.
- **Not a directive executor**: does not execute directives; execution lives in the text-cli runtime.

**Honest notes:**
- Phase orchestration currently advances with **Chinese reasoning resources** (`handle(..., lang="zh")` single-locale hardcoded) — this is an **internal behavior** unrelated to the input language (input can be any language).
- Anthropic-downstream SSE (OpenAI upstream → Anthropic downstream) is planned for a later version.

> 'Phase orchestration single-locale hardcoded' means the LLM reasons with Chinese reasoning resources — an internal behavior unrelated to the input language. Multi-language support will be opened once fully stabilized.

---

## Trust & security boundaries

**No intranet assumption**: `auth.enabled=true` by default (user-ID validation on); `required=false` means "validate if present, allow if absent", `required=true` enforces validation (missing valid user-id → 401).

- **Token dual track**: `x-synthloop-token` (user/service/admin scopes, sha256-hash validation, verify permission first) + `x-synthloop-user-id` (identity, attribute after).
- **Admin scope**: the runtime-endpoint management API `/api/v1/runtime-endpoints` requires admin scope; ordinary tokens → 403.
- **Downstream LLM key**: configured in `config.yaml` under `downstream_llm.api_key`; prefer `${ENV_VAR}` environment-variable injection, never hardcode in the repo.
- **tc tokens**: runtime-table tokens encrypted at rest (`SELF_TOKEN_ENC_KEY`) + admin API returns masked values.

---

## License

**Apache 2.0** · [LICENSE](LICENSE) · [GitHub](https://github.com/weihai-limh/synth-loop)
