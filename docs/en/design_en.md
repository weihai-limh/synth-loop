# synth-loop Design Document

> **Doc type**: Technical design
> **Version**: v0.1.2_e | **Date**: 2026-08-29
> **Scope**: synth-loop
> **Related docs**: `product_zh.md`, `api_zh.md`
>
> This document answers "how it is built". All designs are grounded in the code as truth.

---

## 1. Core positioning

synth-loop is a **task-processing hub exposed as an LLM gateway** — externally it wears the "face" of an LLM gateway (OpenAI/Anthropic-compatible endpoints); internally it is a switching hub that dispatches and converges: for every request it makes the full set of decisions (which path, which model, which context, which gate, how to reason multi-step), finally converging all of that inference to a single inference point (`sl_llm_provider`).

```
API proxy:   request → forward → response (semantics unchanged)
synth-loop:  request → fractal routing (pick one path) → context kernel (ck assembly + gate) → task-chain inference → single inference point → streaming response
```

### What it is / is not

| Is | Is not |
|------|------|
| Task-processing hub — dispatch + converge (`src/sl-py/app/services/sl_llm_provider.py` single inference point) | Matching engine (strategy matching is handled by the external strategy service) |
| Protocol-compatible endpoint — OpenAI + Anthropic dual-protocol entry (`src/sl-py/app/services/protocol_translator.py`) | API proxy / neutral gateway — no request passthrough; every request goes through orchestration decisions |
| Context-kernel host — ck six-layer assembly + gate listening (`src/sl-py/app/kernels/context_kernel/`) | LLM framework (does not wrap LLM calls) |
| Task handler — fractal routing, phase reasoning (pk), unified gate management, unified data plane | Strategy owner (strategy is managed by the external strategy service) |

---

## 2. System architecture

### 2.1 Deployment topology

```
┌──────────────┐     OpenAI/Anthropic      ┌──────────────────┐
│  Any Agent   │ ──────────────────────→   │   synth-loop     │
│  (client)    │                           │   localhost:13155 │
└──────────────┘                           └────────┬─────────┘
                                                    │
                          ┌─────────────────────────┼─────────────────────┐
                          ▼                         ▼                     ▼
              ┌────────────────────┐    ┌────────────────────┐  ┌──────────────────┐
              │   strata-match     │    │   downstream LLM   │  │    text-cli       │
              │   localhost:13156  │    │  OpenAI/Anthropic  │  │  directive engine │
              │  strategy + prompt │    │                    │  │                   │
              └────────────────────┘    └────────────────────┘  └──────────────────┘
```

**Design basis** (`src/sl-py/app/config.py` `PROJECT_ROOT` / `DEPLOY_DIR` / `SRC_DIR` path constants): the three components are decoupled over HTTP; each layer evolves and is replaceable independently. synth-loop consumes strata-match output without depending on its internals; it degrades gracefully when unavailable.

### 2.2 Planes / layers

| Plane | Component | Responsibility | Code location |
|------|------|------|---------|
| **User plane** | external client | issues requests over the OpenAI/Anthropic protocols | external, or the shell `src/sl-web-chat/` |
| **Orchestration plane** | synth-loop | fractal decision, strategy injection, task-chain advancement, SSE streaming | `src/sl-py/` |
| **Strategy plane** | strata-match | prompt matching, skills fragments, tool definitions, Assets | external service |
| **Execution plane** | text-cli | distributed directive execution, capability discovery | external service |
| **Admin plane** | admin panels + event bus | session monitoring, task-chain tracking, Job management | `src/sl-py/public/` + `src/sl-py/app/routers/admin.py` |

### 2.3 External dependency interfaces

| External service | Endpoint | Auth | Call paradigm | Code reference |
|---------|------|------|---------|---------|
| strata-match | `POST /api/v1/query` | none (intranet) | HTTP JSON request/response | `src/sl-py/app/services/strata_match_client.py` |
| strata-match | `POST /api/v1/users` | none | HTTP JSON (linked registration) | `src/sl-py/app/routers/admin.py` |
| strata-match | `POST /api/v1/jobs` | none | HTTP JSON (open/close) | `src/sl-py/app/services/job_store.py` |
| downstream LLM | `POST /v1/chat/completions` | API Key | OpenAI-compatible HTTP | `src/sl-py/app/services/downstream_llm.py` |
| text-cli | `POST /text-cli/cli` (routed via the runtime table) | intranet | HTTP JSON | `src/sl-py/app/services/textcli_enhanced_client.py` |

---

## 3. Mainline service design

### 3.1 Router layer (`src/sl-py/app/routers/`)

| Capability | Implementation | Notes |
|------|------|------|
| OpenAI entry | `chat.py` — `chat_completions()` + dispatch decision chain | `/v1/chat/completions` |
| Anthropic entry | `anthropic_chat.py` — request translation + dispatch | `/v1/messages` |
| Packet data plane | `packets.py` — context packet submit + validation | `/v1/packets` |
| Permanent-channel packet | `longdata.py` — doc/memory add/delete/list | `/v1/longdata` |
| Health check | `health.py` | `/health` |
| Async task API | `tasks.py` — GET + POST cancel | `/api/v1/tasks/{id}` |
| Runtime-table management API | `runtime_endpoints.py` — CRUD | `/api/v1/runtime-endpoints` (admin scope) |
| Artifact data plane | `artifacts.py` — phase artifact query | `/api/v1/artifacts/{id}`, `?pipeline_id=` |
| Unified-gate hook surface | `gate.py` — gate_manager config (new in _b) | `/gate-manager/config` GET/PATCH |
| Admin panels | `admin.py` — HTML page routes | `/admin/sessions` etc. |

### 3.2 Orchestration service layer (`src/sl-py/app/services/`)

| Capability | Implementation | Notes |
|------|------|------|
| Complexity classification | `complexity_classifier.py` | rule matching → chat / task_chain / fractal |
| Execution routing | `execution_router.py` | fractal decision + model selection + downstream call orchestration |
| Task chain service | `task_chain_service.py` | single-step loop: write tasks table (queued) → delegate text-cli `--async` → poll → confirm gate (internal `_dispatch_confirm`) → write back (completed/error); inherits G3 persistence responsibility |
| Context injection | `context_injector.py` | task-chain step context injection (completed steps + current step) |
| Context compression | `context_compressor.py` | upstream filtering — three-state handling of system messages by complexity |
| Context tag management | `context_manager.py` | per-tag load/unload/list/refresh of the permanent-zone context |
| Streaming | `streaming_handler.py` | OpenAI + Anthropic SSE format output |
| Protocol translation | `protocol_translator.py` | Anthropic ↔ OpenAI format conversion |
| strata-match client | `strata_match_client.py` | HTTP client + cache + mock |
| Tool adapter | `strata_match_tool_adapter.py` | strata-match tools → OpenAI format |
| Tool dispatcher | `tool_dispatcher.py` | register + route tool calls |
| Dynamic tool execution | `dynamic_tool_executor.py` | runtime tool execution (goes through the enhanced client, no `command.replace`) |
| Degradation manager | `degradation_manager.py` | three-tier degradation logic |
| Model selector | `model_selector.py` | passes service straight through to execution_router (_b: llm_routing config = single source of truth, no service_map whitelist truncation) |
| Single inference point | `sl_llm_provider.py` | all paths (main/phase/tool) converge; generic service selection + ck gate integration + context_id generation |
| Inference seam | `inference_seam.py` | `SlInferenceSeam`: pk inference seam, exposed to build_messages, assembled by ck + gate listening |
| Unified gate | `gate_manager.py` | cross-kernel gate orchestration: five GateTypes + combo-function registry + cross-kernel loop + ck/pk port adapters |
| Kernel adapter layer | `kernel_adapters.py` | sl-side ck components (SlContextKernel/adapters) + pk assembly (build_phase_engine) + `_PkGateAdapter` (_e wired to the real `PhaseGateExecutor`: async bridging + self-implemented query on the controlled phase surface) |
| Logic abstractor | `logic_abstractor.py` | keyword-based subtype determination |
| Session manager | `session_manager.py` | Session CRUD + expiry cleanup |
| DB writer | `db_writer.py` | async event-log writes |
| Job store | `job_store.py` | cross-component Job coordination |
| Packet store | `packet_store.py` | in-memory cache + TTL auto-cleanup + type validation (type allow-list config-driven via `packets.types`, empty config falls back to built-in default) |
| Preprocessors | `preprocessors.py` | per-type preprocessing to extract summaries |
| Permanent-zone data plane | `longdata.py` | Channel B (permanent): doc/memory add/delete/list, into the longdata table + permanent zone |
| Phase artifact bridge | `sl_artifact_store.py` | Link C: implements the pk `ArtifactStore` port, persisted to sl SQLite |
| Runtime table | `runtime_endpoints.py` | tc endpoint config surface: seed idempotency + CRUD + token encryption/masking + alias routing/degradation |
| Enhanced client | `textcli_enhanced_client.py` | tc execution surface: four functions + SPEC 1.3.2 envelope direct-read + rank degradation + no auth degradation |
| Phase orchestrator | `phase_chat_orchestrator.py` | phase chat contract: thin-shell delegation to pk `PhaseReasoningEngine` (assembled by build_phase_engine; _e wired to sm: planner=PhasePlanPlanner, url from config.strata_match.url; `handle(..., lang="zh")` single-locale hardcoded); sl's own state machine retired |
| Phase kernel | `kernels/phase_kernel/` | vendored — pk components: fractal phase tree + three gates + checkpoint + inference seam (filled by SlInferenceSeam) + sm seam (SmStrategyBundle structured policy; _e copied into sl) + i18n (`i18n/*.json` + `core/i18n.py` loader, sl single-locale default zh; no serve/) |
| Context kernel | `kernels/context_kernel/` | vendored — ck components: six-layer assembly + reasoning gate + gate_mode (pure copy, wrapped by the sl adapter layer) |
| Artifact data plane | `artifact_dataplane.py` | phase artifacts persisted: artifacts table + TTL 24h (pk ArtifactStore adapter; artifact_id unique & required, the rest nullable, phase_index_txt stores phase_path, content supports str/dict) |
| Token service | `token_service.py` | unified token: issue_token / verify_token / map_user_id |

### 3.3 Tool layer (`src/sl-py/app/tools/`)

| Capability | Implementation | Notes |
|------|------|------|
| Expert prompt selection | `select_system_prompt.py` | pick a persona by intent |
| Document load | `load_document.py` | load into the permanent context zone |
| Document unload | `unload_document.py` | remove from the context zone |
| text-cli discovery | `discover_textcli.py` | discover available directives (v0.1.2_a: via the enhanced client discover) |
| text-cli call | `call_textcli.py` | execute a directive (v0.1.2_a: via the enhanced client call) |

---

## 4. Data flow design

### 4.1 Request flow (hot path)

```
Client → POST /v1/chat/completions
  │
  ├── auth middleware (enabled/required config) → x-synthloop-user-id validation → 401 or continue
  │    code: src/sl-py/app/middleware/auth.py
  │
  ├── [optional] session reuse → session_manager.get_or_create()
  │    code: src/sl-py/app/services/session_manager.py
  │
  ├── message pre-check layer
  │     ├── Task-(.+)-synthloop match → query tasks table → terminal response
  │     ├── <user-memory>...</user-memory> match → extract → write to permanent zone
  │     └── phase routing: synth_pipeline field present → parse action → pk phase reasoning (thin-shell delegation)
  │    code: src/sl-py/app/routers/chat.py chat_completions()
  │
  ├── complexity classification
  │     ├── Tier 1: rule matching (<1ms, 0 token)
  │     └── Tier 2: fractal prompt (1 LLM call)
  │    code: src/sl-py/app/services/complexity_classifier.py
  │
  ├── phase pre-intercept: phase XML tags hit → route directly to pk phase reasoning (skips fractal)
  │     ├── <tc-phase>target</tc-phase>           → structural fractal (complex)
  │     └── <tc-phase-chain>target</tc-phase-chain> → chain fractal (medium)
  │    (tag explicitly locks; tag-inner text is the phase target; no tag → fractal routing ↓)
  │
  ├── fractal routing (pick one path; phases not in this list)
  │     ├── a/chat → direct answer
  │     ├── b/prompt_chat → strata-match strategy query → inject
  │     ├── c/task → strata-match tool injection → LLM tool-call loop
  │     └── e,f/task_chain → task-chain decomposition & execution
  │    code: src/sl-py/app/routers/chat.py chat_completions() dispatch decision chain
  │
  ├── main-path merge: all branches converge via build_messages → sl_llm_provider (single inference point)
  │     ├── context assembled by ck + gate listening (gate_mode=auto parks and returns pending, peek/amend)
  │     └── model via llm_routing multi-scenario config (service passthrough, no whitelist truncation)
  │    code: src/sl-py/app/services/sl_llm_provider.py + kernels/context_kernel/
  │
  └── SSE streaming response
       code: src/sl-py/app/services/streaming_handler.py
```

### 4.1.1 Error & degradation paths

| Scenario | Behavior | Code |
|------|------|------|
| strata-match timeout (>5s) | auto-degrade to default prompt | `degradation_manager.py` |
| strata-match returns error | auto-degrade to default prompt | `degradation_manager.py` |
| tool call failure | inject error info, LLM handles it | `tool_dispatcher.py` |
| 3 consecutive tool failures | circuit break; subsequent calls auto-degrade | `tool_dispatcher.py` CircuitBreaker |
| downstream LLM unavailable | return 502 | `downstream_llm.py` |

### 4.2 Config flow (cold path)

```
config.yaml ──→ load_config() ──→ get_section() / get_*_settings()
  │                                  │
  │  src/sl-py/app/config.py         ├── get_config() → global cache
  │                                  ├── get_section("strata_match")
  │                                  ├── get_auth_settings()
  │                                  ├── get_session_memory_settings()
  │                                  └── get_async_task_settings()
  │
  ├── complexity_rules.yaml ──→ ComplexityClassifier.load_rules()
  ├── model_config.yaml ────→ ExecutionRouter.load_config()
  └── .env (optional) ────→ _resolve_env_vars()
```

### 4.3 Data-plane flow (endpoint → validate → preprocess → inject)

```
User message → chat_completions()
  ├── validate: messages format / model name / stream flag
  ├── pre-check: message pre-checks (Task-ID / user-memory)
  ├── classify: ComplexityClassifier.classify()
  ├── enhance: strata-match query → primary_prompt + tools + assets
  ├── inject: ck kernel assembly → <context> XML context assembly
  │          <context>
  │            <strategy>...</strategy>
  │            <user-memory>...</user-memory>
  │            <references>...</references>
  │            <session>...</session>
  │          </context>
  └── reason: downstream_llm.chat() / TaskChainService.run() (v0.1.2_d: old TaskChainExecutor removed, driven by TaskChainService single-step loop)
```

### 4.4 Dual-channel data plane

> **Essence**: the data plane is divided by **permanent vs temporary**, not by doc/memory vs packets. Two channels split by persistence.

```
┌─────────────────────────────────────────────────┐
│ Data plane — dual channel (split by persistence) │
├─────────────────────────────────────────────────┤
│  Channel A: temporary channel (packets · existing)│
│    entry   : /v1/packets                         │
│    payload : environment context (browser/mini-program/IM/IoT) │
│    types   : config allow-list (packets.types, _c)│
│    process : preprocessors (code-level, per-type extraction) │
│    storage : memory + TTL (transient, 30min expiry)│
│    inject  : summary into system prompt          │
├─────────────────────────────────────────────────┤
│  Channel B: permanent channel (/v1/longdata · new in _c)│
│    entry   : /v1/longdata (add/del/list)         │
│    payload : doc (document) + memory (memory snippet) │
│    types   : hardcoded (doc/memory two types)    │
│    process : generic text processing (strip whitespace etc.) │
│    storage : longdata table + permanent zone (long-lived) │
│    inject  : from the permanent zone via build_messages │
└─────────────────────────────────────────────────┘
```

**Link C phase-artifact bridging**: pk engine writes artifacts via `SlArtifactStore` (implementing the pk `ArtifactStore` port) into the sl SQLite `artifacts` table — artifacts are no longer memory-only, `/v1/artifacts` is externally fetchable, and cross-phase context passing (`_fetch_parent_context`) links back via `fetch`.

---

## 5. Unified terminal contract

### External API endpoints

| Endpoint | Protocol | Method | Auth | Code |
|------|------|------|------|------|
| `/v1/chat/completions` | OpenAI | POST | none (optional Bearer) | `chat.py` |
| `/v1/messages` | Anthropic | POST | none (optional x-api-key) | `anthropic_chat.py` |
| `/v1/packets` | JSON | POST | none | `packets.py` |
| `/v1/longdata` | JSON | POST/DELETE/GET | none | `longdata.py` |
| `/api/v1/runtime-endpoints` | JSON | GET/POST/PATCH/DELETE | admin scope | `runtime_endpoints.py` |
| `/api/v1/artifacts/{id}` | JSON | GET | none | `artifacts.py` |
| `/api/v1/artifacts?pipeline_id=` | JSON | GET | none | `artifacts.py` |
| `/health` | JSON | GET | none | `health.py` |
| `/admin/sessions` | HTML | GET | none | `admin.py` |
| `/admin/tasks` | HTML | GET | none | `admin.py` |
| `/admin/jobs` | HTML | GET | none | `admin.py` |
| `/admin/users` | HTML | GET | none | `admin.py` |
| `/admin/listeners` | JSON | POST/GET/DELETE | none | `admin.py` |
| `/admin/analysis` | JSON | GET | none | `admin.py` |
| `/api/v1/tasks/{id}` | JSON | GET | none | `tasks.py` |
| `/api/v1/tasks/{id}/cancel` | JSON | POST | none | `tasks.py` |
| `/gate-manager/config` | JSON | GET/PATCH | none | `gate.py` |

### Internal inter-service contract

| Caller → Callee | Interface | Protocol | Timeout |
|------------------|------|:----:|:----:|
| synth-loop → strata-match | `POST /api/v1/query` | HTTP | 5s |
| synth-loop → strata-match | `POST /api/v1/users` | HTTP | 5s |
| synth-loop → strata-match | `POST /api/v1/jobs` | HTTP | 5s |
| synth-loop → downstream LLM | `POST /v1/chat/completions` | HTTP | configurable |
| synth-loop → text-cli | `POST /text-cli/cli` | HTTP | configurable |

---

## 6. Config & persistence design

### 6.1 Config file topology

```
src/sl-py/
├── config.yaml            ← main config (service, auth, session_memory, async_tasks)
├── model_config.yaml      ← model endpoint pool + LLM routing
└── complexity_rules.yaml  ← fractal rules (cover only the two extremes)

src/sl-py/
└── data/
    └── gateway.db         ← SQLite persistence (aiosqlite)
```

### 6.2 Config table

| Config section | File | Default | Code consumer |
|--------|------|--------|-----------|
| `strata_match` | `config.yaml` | url=localhost:13156, mock=false | `strata_match_client.py` |
| `runtime_endpoints` | `config.yaml` | enabled=true, default_alias, seeds (v0.1.2_a, replaces the old `textcli` section) | `runtime_endpoints.py` |
| `pipelines_api` | `config.yaml` | enabled=false (v0.1.2_a 9-endpoint switch; section retained, no corresponding router implementation yet) | — |
| `downstream_llm` | `config.yaml` | api_base, api_key, default_model | `downstream_llm.py` |
| `auth` | `config.yaml` | enabled=true, required=false (no intranet assumption, user-ID validation on by default) | `middleware/auth.py` |
| `session_memory` | `config.yaml` | enabled=true | `routers/chat.py` |
| `async_tasks` | `config.yaml` | enabled=true, max_per_user=3 (v0.1.2_d: service-level async switch on) | `routers/chat.py` |
| `packets` | `config.yaml` | enabled=true, ttl_seconds=1800, types=13-item allow-list (_c) | `packet_store.py` (v0.1.1; _c type allow-list config-driven) |
| `endpoints` | `model_config.yaml` | endpoint pool definitions | `execution_router.py` |
| `llm_routing` | `model_config.yaml` | routing map (_b: multi-scenario single source of truth, any service passthrough without whitelist truncation) | `execution_router.py` → `model_selector.py` → `sl_llm_provider.py` |
| `llm_gateway` | `model_config.yaml` | enabled=false, gateways (multi-gateway registry, disabled by default) | `downstream_llm.py` |
| `rules` | `complexity_rules.yaml` | chat/task_chain rules | `complexity_classifier.py` |
| `logic_categories` | `model_config.yaml` (key ⊆ `complexity_rules.yaml` subtypes source) | B3 logic categories externalized: fine-grained route hit → direct lookup; enum validation (key must be a subset of the subtypes source) | `execution_router.py` / `model_selector.py` (v0.1.2_d) |

### 6.3 Persistence

| Table | File | Purpose | Row cap |
|----|------|------|:---------:|
| `session_snapshots` | `gateway.db` | session persistence (permanent_system_prompt, temp_history, snapshot) | none |
| `message_logs` | `gateway.db` | message records (session_id/round_number/direction request\|response/payload) | none |
| `job_store` | `gateway.db` | Job storage (event-bus listeners etc.: job_type/status/config_json/result_json) | none |
| `events` | `events.jsonl` (file, not a DB table) | event log (for `/admin/analysis` offline analysis) | none |
| `users` | `gateway.db` | user auth (v0.1.1) | none |
| `tasks` | `gateway.db` | async tasks (v0.1.1); **rewritten in v0.1.2_d**: old `TaskChainExecutor` removed, persistence responsibility taken over by `TaskChainService.run()` (queued→running→completed/error state machine, serial writes via the unified `get_shared_db()` connection), confirm gate is internal private `_dispatch_confirm` (non-hard dependency) | none |
| `runtime_endpoints` | `gateway.db` | tc endpoint config surface (v0.1.2_a): alias multi-physical-row + rank degradation + token encryption | none |
| `artifacts` | `gateway.db` | phase artifacts (v0.1.2_a; _c relaxed): artifact_id unique & required, the rest nullable, phase_index_txt stores phase_path, content supports str/dict, TTL 24h | none |
| `longdata` | `gateway.db` | permanent-channel (v0.1.2_c): doc/memory introduction (id/session_id/type/content/created_at), no TTL | none |
| `tokens` | `gateway.db` | unified token (v0.1.2_a): sha256 hash + scope tiers | none |

---

## Security design

### Threat assumptions

| Assumption | Impact | Current measure |
|------|------|---------|
| Malicious client forges user-id | medium — multi-tenant scenarios | enforced when `auth.enabled=true, required=true` |
| Downstream LLM API Key leak | high — financial loss | Key configured in config.yaml, environment-variable injection recommended |
| tc token leak | high | runtime-table token encryption (`SELF_TOKEN_ENC_KEY`) + admin API masking + admin scope |

**Worst-case reasoning**: config.yaml leaks → attacker can call the downstream LLM and incur cost. Mitigation: production uses `${ENV_VAR}` environment-variable injection (built-in support via `_resolve_env_vars()`, see `src/sl-py/app/config.py`).

### Network layering / terminal security / privacy compliance

| Dimension | Measure |
|------|------|
| Network layering | controlled by `auth.enabled` config, on by default (no intranet assumption); `required=false` means "validate if present, allow if absent" |
| Session isolation | `x-synthloop-session-id` isolates sessions; `x-synthloop-user-id` isolates users |
| Token dual track | `x-synthloop-token` (user/service/admin scope) verifies permission → `x-synthloop-user-id` attributes identity; runtime-table management API requires admin scope |

---

## Non-functional design

### Observability

| Capability | Implementation | Details |
|------|------|------|
| Event bus | `POST/GET/DELETE /admin/listeners` | every dispatch decision, strata-match call, and task-chain step is pushed |
| Admin panels | `public/sessions.html`, `tasks.html`, `jobs.html` | auto-refresh 5s/10s |
| Event log | `events.jsonl` | persisted, for `/admin/analysis` offline analysis |
| Logging | Python logging | global logger + module-level instances |

### Degradation strategy

| Level | Condition | Behavior | Code |
|:----:|------|------|------|
| L1 | strata-match available | full Prompt + Tools + Assets | — |
| L2 | strata-match unavailable | default Prompt + built-in meta tools | `degradation_manager.py` |
| L3 | downstream LLM unavailable | return 502 | `downstream_llm.py` |

### Reliability

| Mechanism | Notes |
|------|------|
| Stateless core | ComplexityClassifier / ModelSelector / LogicAbstractor are all stateless |
| Session expiry cleanup | auto-cleaned after 3 days of inactivity by default (`session_manager.py`) |
| Circuit breaking | circuit opens after 3 consecutive tool failures (`tool_dispatcher.py` CircuitBreaker) |
| Degradation floor | synth-loop does not crash when any external dependency is unavailable |

---

## Design principles

| Principle | Meaning | Embodiment |
|------|------|------|
| **Fractal decision** | cost fractalizes by complexity; "hello" consumes no strategy matching | `complexity_classifier.py` rules + LLM tiers |
| **Strategy/execution separation** | synth-loop orchestrates, strata-match supplies strategy, text-cli executes | three-layer decoupled architecture |
| **Degradation over unavailability** | auto-degrade when an external dependency is down | `degradation_manager.py` three-tier degradation |
| **Single source of truth** | rules→yaml, models→yaml, config→yaml | `complexity_rules.yaml`, `model_config.yaml`, `config.yaml` |
| **Stateless components first** | core decision components hold no state | ComplexityClassifier / ModelSelector / LogicAbstractor |
| **Dispatch is a pattern, not an API** | embedded in existing endpoints, no new routes | fractal decision embedded inside `/v1/chat/completions` |

---
