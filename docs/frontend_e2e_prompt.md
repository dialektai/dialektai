# Frontend E2E Test Prompt (queued for tomorrow)

See the original prompt in the session transcript on 2026-04-23 evening.
Key bits:
- 10 sections × ~95 checklist items
- Chrome MCP or Playwright headed mode required
- Clean ~/.dialekt/ before starting (use separate HOME=/tmp/fresh profile
  to preserve current working state)
- Expected time: 1–2 hours hands-on
- Report format: Executive Summary + 10 section details + screenshots

Preconditions checklist (verify before running):
- [ ] Chrome MCP extension reconnected (check tabs_context_mcp works)
- [ ] Local display available (else: run on founder's machine)
- [ ] dialekt-server running on :8765 (or use pm2 dialekt-api)
- [ ] https://dialekt-cloud.dias.now/health → 200
- [ ] Ollama running on :11434
- [ ] `HOME=/tmp/fresh` profile prepared (keeps real state intact)
