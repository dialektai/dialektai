# What dialekt does today

**Version:** v0.10.0 (PR #2 merge — 47 commits, merged 2026-04-24)
**Date:** 2026-04-24
**Status:** Pilot-ready

> This is the **executive pilot-facing summary**. For the full catalog of working agents and their sample queries, see [`AGENT_CATALOG.md`](AGENT_CATALOG.md).

---

## In one sentence

Платформа для создания локальных AI-агентов, работающих в инфраструктуре компании без передачи данных в облачные сервисы.

(In English: a platform for building local AI agents that run inside a company's own infrastructure without sending data to cloud providers.)

---

## What you can build today (verified working)

Every item below is exercised end-to-end on v0.10.0 with a real chat turn captured in `scripts/pilot_verify/evidence.json`. No simulations. Details per agent in [`AGENT_CATALOG.md`](AGENT_CATALOG.md).

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

**Total in catalog:** 10 verified working configurations across 5 categories. Add your own by remixing the manifests — see [`SETTINGS_COMBOS_TODAY.md`](SETTINGS_COMBOS_TODAY.md) for field combinations that will pass validation and fire at runtime.

---

## Setup time per agent

~10 minutes from Builder Wizard to first working query:

1. Add database connection if needed (3 minutes) — Settings → Connections
2. Builder Wizard (5 minutes) — 9 steps with smart defaults
3. Settings → Agents → bind the connection to the agent (1 minute)
4. Open chat, ask the first question

Every step is dialekt-native, no external config files or deployment pipeline.

---

## What's in v0.10.0

- 5/5 CI workflows green: `ci.yml`, `integration-mysql.yml`, `integration-clickhouse.yml`, `integration-postgres.yml`, `e2e.yml`
- 440+ passing tests in `python/tests/` + `dialekt-cloud/tests/`
- 35/35 multi-role E2E scenarios green (Admin × Developer × End-User)
- Plugin architecture consolidated into `dialekt.llm._plugin_context.PluginContext` — in-process ASGI dispatch for tests, HTTP for production, single lazy-init singleton with threading-safe replace/close semantics
- Schema distribution via GitHub tags (no PyPI dependency — works in locked-down corporate networks)
- Multi-role findings closed: UF-1 (plugin hardcoded URL), ADM-1 (tenant status filter), P1 (TOCTOU race), P1.5 (close leak), P2 (loose E2E assertion)

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
| Scheduled / cron agents | ❌ schema-valid, no runtime | M2 (Q3 2026) |
| Webhook triggers | ❌ not a schema variant | M3 (Q4 2026) |
| Multi-agent workflows (A → B) | ❌ one agent per WS session | M3 |
| Vision capabilities | ❌ no vision Ollama model installed | M2 |
| Web search integration (Tavily/Brave/etc.) | ❌ no adapter | M2 |
| Email / SMTP send | ❌ no transport | M2 |
| Browser automation (Selenium) | ❓ code exists, untested on Linux | M2 (verify) |
| Per-agent secrets UI | ❌ `secrets_required` is advisory | M2 |
| Custom manifest variables (anything beyond `{{connection_id}}`) | ❌ not substituted at runtime | M2 |
| Output destinations (`filesystem`, `webhook`, `email_or_telegram`) | ❌ schema-valid, no delivery | M2 |
| Capability checkboxes as a security boundary | ⚠️ advisory metadata, not a sandbox | M2 (per-agent sandboxing) |

These gaps are documented in detail in [`CAPABILITIES_INVENTORY.md`](CAPABILITIES_INVENTORY.md). The rule: do not promise anything in this table for pilots starting before Q3 2026.

---

## Live verification (any pilot can check)

- Download: https://dialekt.dias.now
- Backend health (self-hosted cloud tenant): `GET https://dialekt-cloud.dias.now/health`
- Source: https://github.com/dialektai/dialektai
- Release notes: https://github.com/dialektai/dialektai/releases/tag/v0.10.0
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
- [`AGENT_CATALOG.md`](AGENT_CATALOG.md) — 10+ verified agent configurations with sample queries
- [`TOOLS_AVAILABLE_TODAY.md`](TOOLS_AVAILABLE_TODAY.md) — what an agent's code can call
- [`SETTINGS_COMBOS_TODAY.md`](SETTINGS_COMBOS_TODAY.md) — manifest fields that work at runtime
- [`CAPABILITIES_INVENTORY.md`](CAPABILITIES_INVENTORY.md) — developer-level deep dive
- [`MULTI_ROLE_E2E_REPORT.md`](MULTI_ROLE_E2E_REPORT.md) — the 35/35 multi-role sweep behind v0.10.0
