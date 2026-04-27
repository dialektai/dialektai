# dialekt — Claude Code guidance

Project-local instructions for Claude Code working on dialekt.

## Naming: dialekt (working) vs dias.now (production)

- **`dialekt`** is the **working name** — used in code identifiers, file
  paths, package names, module names, repo name (`dialektai/dialektai`),
  database names (`dialekt_cloud`, `dialekt_cloud_test`), Python imports
  (`from dialekt_cloud import ...`), CLI commands (`dialekt-admin`).
  Don't rename these — they are internal identity, not brand.
- **`dias.now`** is the **production / user-facing brand**. Use it in
  every visible string the customer will see: landing copy, email
  subjects/bodies, SMTP `From:` display names (`dias.now <hello@dias.now>`),
  legal documents, app UI strings, invoices, OG / SEO meta, support
  inboxes (`hello@dias.now`, `security@dias.now`).
- When in doubt: if a developer reads it → `dialekt`. If a customer
  reads it → `dias.now`.

The repo-wide rename happened on the `ux-ui` branch — every literal
`dialekt.ai` string was replaced with `dias.now`. Don't reintroduce
`dialekt.ai` in user-visible copy.

## When to invoke mentor agent

Use the `Task` tool с `subagent_type="mentor"` для the following scenarios:

- **Architectural decisions** — design docs, transport choices, module
  structure, trade-off analysis
- **Strategic priorities** — what to build next, what to defer, what to cut
- **Code review** — before commit для complex changes, before PR merge
- **Scope rulings** — mid-implementation scope questions ("should we also add X?")
- **Go/no-go calls** — release approval, major refactor approval
- **When Dias delegates** — "you decide", "ты знаешь как я думаю",
  "делай что правильно", "что правильно тут", etc.

Do NOT invoke mentor для:

- Trivial fixes (typos, lint, formatting)
- Tests для already-approved architecture
- Running builds / tests / CI
- Direct Dias communication questions (ask Dias directly)

## Invocation pattern

```
Task tool with:
  subagent_type: "mentor"
  description: "MCP server Этап 2 PR review"
  prompt: "[self-contained briefing]
    - What I did: [...]
    - What I need decided: [...]
    - Files to check: [...]
    - Diff: git log --oneline <range>
    Give me your verdict + reasoning. Do not approve без reading diff."
```

The mentor will read files via its own tools, formulate a verdict,
and return structured output (Verdict / Reasoning / Findings / Next step).

## After mentor verdict

- **APPROVE** → proceed as planned
- **NEEDS CHANGES** → address all P0/P1 findings, re-invoke mentor,
  only proceed after APPROVE
- **REJECT** → STOP, surface to Dias with mentor's reasoning. Do not
  attempt to work around

## Quality bar

If mentor suggests a specific approach — execute it fully. Don't
half-implement to save time. The mentor's job is to prevent tech debt;
honoring their decisions keeps the product at 100% completion bar
не halfway-to-something.

When mentor gives a trade-off ("A better but costs Y, willing to pay Y"),
pay Y. Don't silently take the cheaper path and hope no one notices.

## When to invoke dias agent

Use `Task` с `subagent_type="dias"` для quick style / convention
decisions too small to interrupt Dias directly:

- Variable naming preferences (snake_case, short > verbose)
- Commit message wording
- Test type choice (unit vs integration)
- Import ordering / docstring format
- Error message wording в logs / CLI output
- File structure within established patterns

Do NOT invoke dias для:

- Architecture (invoke `mentor`)
- Strategic priorities (invoke `mentor` or escalate to Dias)
- Customer communication (escalate to Dias directly)
- Anything that changes product behaviour (invoke `mentor`)

Dias agent is a style proxy — if the question feels bigger than
"how should this be named", escalate via the agent's own
refusal-then-redirect pattern.

## Related agents

- `code-reviewer.md` — line-level code review (use inline during
  commits, not for architectural questions)
- `debugger.md` — targeted bug hunting when tests fail mysteriously

Layered decision surface:

```
dias         → style / conventions (small)
mentor       → architecture / strategy / PR approval (medium-large)
Dias himself → customer / financial / existential (largest)
```

Invoke the smallest one that can handle the question. Escalate
upward when scope grows mid-decision.
