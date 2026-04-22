# dialekt state, updated 2026-04-22

## Current stage
Stage 2, Week 0 of 13 — not started, first commit pending

## Code state
- `dialektai/dialektai` main: v0.8.2, clean, no WIP branches
- `feat/goal-1-agents`: NOT YET CREATED — next step
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
- [ ] Create `feat/goal-1-agents` branch
- [ ] SQLite schema: `agents` table + `sessions` FK
- [ ] Migration script: existing sessions → "General Assistant" agent
- [ ] CRUD endpoints: GET/POST/PATCH/DELETE /agents
- [ ] Import/export via dialekt-manifest-validator
- [ ] Two app modes (structural): builder vs user
- [ ] First-launch mode selector screen
- [ ] `useAgents.js` hook + "My Agents" sidebar section
- [ ] Tests: agents API, migration

## Founder parallel (this week)
- [ ] Rotate PyPI token
- [ ] Start Stripe KZ verification
- [ ] Contact 3 pilot companies — first outreach

## Energy state
- Scenario A assumed (fulltime, 6-8h/day)
- Week 4-5: reassess scope if falling behind
