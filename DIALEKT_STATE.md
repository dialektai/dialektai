# dialekt state, updated 2026-04-22

## Current stage
Stage 2, Week 1 of 13 — Goal 1 backend in progress

## Code state
- `dialektai/dialektai` main: v0.8.2, clean
- `feat/goal-1-agents`: DB schema + CRUD + REST endpoints + tests ✓
- `dialektai/dialekt-manifest-validator`: v0.1.0 on PyPI, 28/28 tests
- Stage 1 closed: repo, AGENT_MANIFEST_SPEC.md v1.0.1, validator published

## Pilot status
- No pilots contacted yet — outreach pending

## Decisions pending
- PyPI token rotation (shared in plaintext — urgent)
- Cloudflare Tunnel setup for home server (founder task)
- Stripe KZ verification (start now, may take 1-2 weeks)

## Blockers
- None on code side
- Founder parallel tasks not started (Cloudflare, Stripe, Resend)

## This week priorities (Week 1)
- [x] Create `feat/goal-1-agents` branch
- [x] SQLite schema: `agents` table + `sessions` FK
- [x] Migration script: existing sessions → "General Assistant" agent
- [x] CRUD endpoints: GET/POST/PATCH/DELETE /agents
- [x] Import/export via dialekt-manifest-validator
- [x] Two app modes (structural): GET/POST /config/mode
- [x] Tests: agents API, import, migration (42/42 passing)
- [x] First-launch mode selector screen (ModeSetupScreen.jsx)
- [x] `useAgents.js` hook + "My Agents" sidebar (LeftPanel builder mode)
- [ ] Session history grouped by agent (deferred to Week 2)

## Founder parallel (this week)
- [ ] Rotate PyPI token
- [ ] Start Stripe KZ verification
- [ ] Contact 3 pilot companies — first outreach

## Energy state
- Scenario A assumed (fulltime, 6-8h/day)
- Week 4-5: reassess scope if falling behind
