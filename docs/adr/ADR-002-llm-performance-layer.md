# ADR-002: LLM Performance Layer (Goal 8) — transparent prompt optimization

**Date:** 2026-04-22
**Status:** Accepted

## Context

Local LLMs (Ollama, 7B–32B parameter models) are less reliable than cloud APIs:
- More likely to hallucinate table/column names in SQL generation
- Often ignore output format instructions
- Lose context in long sessions (limited context window)
- Improve when given examples of prior successful interactions

Users should not need to configure any of this. It must "just work".

## Decision

Implement a transparent 3-layer optimization pipeline applied before every LLM call:

### Layer 1: Structured prompt templating (Goal 8.1)
`dialekt/llm/prompt_wrapper.py`

Wraps every system prompt in consistent sections:
`## ROLE` / `## LANGUAGE` / `## OUTPUT FORMAT` / `## CONTEXT` / `## HISTORY (summarized)` / `## EXAMPLES`

Per-agent opt-out via `prompt_wrapping: false` in manifest YAML.

### Layer 2: Template variable substitution
`substitute_template_vars()` in prompt_wrapper.py

Replaces `{{connection_id}}`, `{{connection_name}}`, `{{database_type}}` with
values from `agent_bindings` table before the LLM sees the prompt.
Connection binding is set once via `POST /agents/{id}/binding`.

### Layer 3: Self-correcting retry loop (Goal 8.3)
`dialekt/llm/retry_loop.py`

For tool-use agents (SQL Analyst primary):
1. LLM generates tool call (SQL query)
2. `validate_sql()` runs `EXPLAIN` before execution
3. On failure: error feedback injected, LLM regenerates (max 3 retries)
4. User sees only final successful result

## Implementation notes

- `resolve_agent_context()` is async; called in `ws_chat` before `make_interpreter()`
- `agent_bindings` SQLite table stores connection binding per agent
- Prompt wrapping is applied in `make_interpreter()` — agents never see raw prompt
- `should_wrap()` checks for `prompt_wrapping: false` in manifest YAML

## Consequences

**Good:**
- SQL queries validated before execution — fewer confusing error messages
- Template substitution means SQL Analyst "knows" which DB to use automatically
- Structured prompts improve output format compliance (especially for markdown tables)

**Bad:**
- Adds one extra API call per query (EXPLAIN for SQL validation)
- `make_interpreter()` now requires `agent_context` dict from async DB lookup
- Prompt wrapping adds ~300 tokens to every system prompt

## Review trigger

Re-evaluate retry loop if:
- EXPLAIN adds > 200ms p95 latency
- Models improve enough that retry is never needed

Re-evaluate prompt wrapping if:
- A model performs better without structured sections
- Prompt overhead exceeds 10% of context window regularly
