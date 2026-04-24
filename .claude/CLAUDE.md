# dialekt — Claude Code guidance

Project-local instructions for Claude Code working на dialekt.ai.

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

## Related agents

- `code-reviewer.md` — line-level code review (use inline during
  commits, not for architectural questions)
- `debugger.md` — targeted bug hunting when tests fail mysteriously

Mentor is the strategic / architectural layer above these — invoke
mentor when the question is "should we build this?" or "does this
fit the architecture?", invoke the others when the question is
"why doesn't this code work?"
