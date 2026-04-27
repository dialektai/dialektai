# What dialekt does today

**Version:** v0.27.0
**Last shipped:** v0.27.0 (2026-04-27) — scheduler, web search, visual engine, IBA pilot agents
**Date:** 2026-04-27
**Status:** Pilot-ready

> This is the **executive pilot-facing summary**. For the full catalog of working agents and their sample queries, see [`AGENT_CATALOG.md`](AGENT_CATALOG.md).

---

## In one sentence

Платформа для создания локальных AI-агентов, работающих в инфраструктуре компании без передачи данных в облачные сервисы.

(In English: a platform for building local AI agents that run inside a company's own infrastructure without sending data to cloud providers.)

---

## What you can build today (verified working)

Every capability below is backed by passing tests in `python/tests/` (846 passing on v0.27.0). Details per agent type in [`AGENT_CATALOG.md`](AGENT_CATALOG.md).

### SQL Analytics agents
PostgreSQL, MySQL, ClickHouse. Natural-language queries in Russian, English, or Kazakh → SQL → table results. Read-only by default, with row-limits and query timeout enforced. Setup per connection: 5 minutes.

### Code review & shell assistants
Python-aware reviewers (qwen2.5-coder:7b), bash command suggesters with safe-by-default autonomy (`review-only`). Setup: 2 minutes.

### Document processing agents
Summarisers (3-bullet extraction), translators covering Russian/English/Kazakh. Pure LLM — no connections, no setup beyond agent creation.

### Conversation agents
General-purpose assistants (the bundled "General Assistant" with ComfyUI image/video generation hooks, shell, Python), domain-specialised writing helpers (Russian editor, etc.). Setup: 2 minutes.

### Multi-tool agents
Combinations — e.g. a Data Engineer helper with simultaneous access to a PostgreSQL connection, the filesystem, and the shell for ETL-style workflows. Setup: 10 minutes.

### MCP-enabled agents (v0.20+)
External Model Context Protocol servers (GitHub, Slack, filesystem, Linear, Figma, etc.) are configurable through Settings → MCP Servers without editing YAML. The Builder Wizard has a new "MCP Tools" step where users tick the servers an agent can call. Destructive tool calls (anything write-shaped) prompt for explicit consent in a chat-overlay modal — three-button decision (Approve once / Approve for session / Deny) with keyboard shortcuts and full audit trail. Credentials live in the OS keychain.

**Real-server validation:** GitHub MCP path validated end-to-end — 10/10 stages green including consent prompt, audit chain linkage, real issue creation, OS-keychain lifecycle. See `docs/MCP_PRODUCTION_VALIDATION.md`.

### Scheduled / cron agents (NEW in v0.27)
Agents can run on a cron schedule and deliver results via Telegram. Set a `scheduled` trigger in the manifest with a standard cron expression (`0 9 * * 1-5` = every weekday at 9 AM). APScheduler handles the runtime. Supports Telegram delivery to a configured `telegram_chat_id` + `telegram_bot_token` stored in the OS keychain.

**Limitation:** email (SMTP) delivery is not yet implemented — Telegram-only in v0.27. Email delivery is targeted for v0.28.

### Web search agents (NEW in v0.27)
Agents can query the web via Tavily, Brave Search, or DuckDuckGo. Configure a provider in Settings → Web Search. Once credentials are set, any agent can call web search via the `web_search` capability group.

### Visual engine — HTML/PNG rendering (NEW in v0.27)
Agents can render HTML templates to PNG images via Playwright/Chromium. Upload a template (Jinja-style `{{KEY}}` variables), call the render endpoint, receive a PNG back. Used for social-media cards, reports, certificates.

---

## Setup time per agent

~10 minutes from Builder Wizard to first working query:

1. Add database connection if needed (3 minutes) — Settings → Connections
2. Builder Wizard (5 minutes) — 9 steps with smart defaults
3. Settings → Agents → bind the connection to the agent (1 minute)
4. Open chat, ask the first question

Every step is dialekt-native, no external config files or deployment pipeline.

---

## What's in v0.27.0

- **846 passing tests** in `python/tests/` (zero failures, 70 env-conditional skips)
- CI jobs: unit tests, cloud tests, integration tests, frontend build — all green
- Scheduler runtime (APScheduler) + cron session + Telegram delivery
- Web search adapter (Tavily / Brave / DuckDuckGo) + Settings UI
- Visual engine (HTML → PNG via Playwright/Chromium) + template registry
- IBA pilot agent templates: `content_editor`, `smm_manager`, `schedule_planner`
- MCP Audit Dashboard (v0.25), Process Resilience health registry (v0.26)
- GPU Relay mode for cloud LLM providers
- Agent Library with cloud-sync catalog
- Invoice billing (KZ legal, ru/en templates)
- LLM performance layer: prompt wrapper, few-shot memory, retry loop

---

## Pricing (reference)

| Tier | Per-seat | Min seats | Min spend | Target |
|---|---|---|---|---|
| **Starter** | $25 / mo | 3 | $75 / mo | Pilots, small teams |
| **Professional** (recommended) | $55 / mo | 5 | $275 / mo | Day-to-day production |
| **Enterprise** | $95+ / mo | 10 | $950+ / mo | Custom SLAs, dedicated support |

Typical pilot: 6 seats × $55/mo = **$330 MRR = $3 960 ARR**.

---

## Honest limitations (tell the pilot)

| Feature | Status | Target |
|---|---|---|
| Scheduled / cron agents | ✅ ships v0.27, Telegram delivery only | v0.28 for email |
| Web search (Tavily / Brave / DDG) | ✅ ships v0.27 | — |
| Visual engine (HTML → PNG) | ✅ ships v0.27 | — |
| Telegram delivery for scheduled agents | ✅ ships v0.27 | — |
| Email / SMTP delivery from scheduler | ❌ not yet | v0.28 |
| Webhook triggers | ❌ not in schema | M3 (Q4 2026) |
| Multi-agent workflows (A → B) | ❌ one agent per WS session | M3 |
| Vision capabilities (image description) | ⚠️ code ready, needs vision model (llava / moondream) installed in Ollama | operator-installed |
| Browser automation (Playwright crawling) | ⚠️ untested for crawling use cases | verify per pilot |
| Per-agent secrets UI | ⚠️ `secrets_required` is advisory, not enforced | M3 |
| Custom manifest variables beyond `{{connection_id}}` | ❌ not substituted at runtime | M3 |
| `model.parameters` in manifest (temperature, max_tokens) | ⚠️ advisory — global settings override; change in Settings → Model | — |
| Capability checkboxes as security boundary | ⚠️ advisory metadata, not a sandbox | M3 |
| Bitrix24 / CRM integrations | ❌ not built | P2, next pilots |
| Replicate image generation UI | ❌ not built | post-pilot |

These gaps are documented in detail in [`CAPABILITIES_INVENTORY.md`](CAPABILITIES_INVENTORY.md).

---

## Live verification (any pilot can check)

- Download: https://dialekt.dias.now
- Backend health (self-hosted cloud tenant): `GET https://dialekt-cloud.dias.now/health`
- Source: https://github.com/dialektai/dialektai
- Release notes: https://github.com/dialektai/dialektai/releases/tag/v0.27.0
- CI dashboard: https://github.com/dialektai/dialektai/actions
- Manifest validator: https://github.com/dialektai/dialekt-manifest-validator

---

## Pilot onboarding path

1. **Discovery call (15 minutes)** — live demo over screen share against the pilot's actual data (or our ecom integration database).
2. **Free trial, 2 months** — dialekt running on the pilot's infrastructure, direct technical support from Dias throughout.
3. **Weekly feedback calls** — what's working, what's missing, what's the blocker on day-to-day adoption.
4. **Conversion** — move to paid plan after 2 months if the team is actively using it. No pressure-sell; if it hasn't stuck, we revisit in a quarter.

**Contact:** hello@dias.now · Telegram: @z_dias_c

---

**See also:**
- [`AGENT_CATALOG.md`](AGENT_CATALOG.md) — verified agent configurations with sample queries
- [`TOOLS_AVAILABLE_TODAY.md`](TOOLS_AVAILABLE_TODAY.md) — what an agent's code can call
- [`SETTINGS_COMBOS_TODAY.md`](SETTINGS_COMBOS_TODAY.md) — manifest fields that work at runtime
- [`CAPABILITIES_INVENTORY.md`](CAPABILITIES_INVENTORY.md) — developer-level deep dive
- [`IBA_PILOT_READINESS.md`](IBA_PILOT_READINESS.md) — IBA-specific readiness report (v0.27)
