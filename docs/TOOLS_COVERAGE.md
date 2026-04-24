# Tools Coverage — Multi-Role E2E 2026-04-24

Which in-agent tools are exercised by the 2026-04-24 multi-role sweep,
and where. Source of truth: the three `python/tests/test_e2e_role_*.py`
files + `dialekt-cloud/tests/test_e2e_role_admin.py`.

| Tool | Where implemented | Exercising test(s) | Status |
|---|---|---|---|
| **DialektSQL — PostgreSQL** | `dialekt/llm/sql_language.py` → `/connections/{id}/query` (postgres_mcp.py) | `role_developer.test_01`, `role_developer.test_04`, `role_user.test_02`, `role_user.test_03`, `role_user.test_08` | ✅ REST-level covered<br>⚠ chat-level blocked by **finding UF-1** — see report |
| **DialektSQL — MySQL** | `mcp_servers/mysql_mcp.py` | `role_developer.test_02`, `role_developer.test_06` | ✅ REST-level covered |
| **DialektSQL — ClickHouse** | `mcp_servers/clickhouse_mcp.py` | `role_developer.test_03`, `role_user.test_10` | ✅ REST-level covered<br>⚠ chat-level blocked by UF-1 |
| **Python via Open Interpreter** | OI built-in; triggered by capability `shell_execute` in manifest | `role_developer.test_08` (publish), `role_user.test_01` / `test_07` (default chat turn may invoke code block) | ⚠ publish-level only; chat-level tool fire-rate is LLM-dependent, not asserted |
| **Shell via Open Interpreter** | OI built-in; capability `shell_execute` | `role_developer.test_07` (publish), gated on `DIALEKT_E2E_ALLOW_SHELL=1` for chat-level | ⚠ publish-level only; chat gated |
| **Filesystem read** | OI built-in; capability `filesystem_read` | `role_developer.test_07` | ⚠ publish-level only |
| **Schema RAG (`/connections/{id}/search`, `/reindex`)** | `mcp_servers/schema_rag.py` | `role_developer.test_14` | ✅ REST endpoint reachable; content-level match depends on Ollama `nomic-embed-text:v1.5` being pulled |
| **Schema reload endpoint** | `server.py:482` | `role_developer.test_12`, overnight suite | ✅ |
| **Connection test endpoint** | `/connections/{id}/test` per driver | `role_developer.test_01/02/03`, `role_developer.test_13` (negative) | ✅ |
| **Few-shot memory** | `dialekt/llm/few_shot_memory.py` | none — **deferred to M2** per plan §6 | ⏭ |
| **HTTP tool (agents calling external APIs via Python httpx)** | OI-generated code | none — **deferred to M2** per plan §6 | ⏭ |
| **Browser / Selenium** | OI built-in + `browser` capability | none — practically untestable headless; **deferred** | ⏭ |
| **Screen capture / vision** | OI + `screen_capture` capability | none — no display in CI; **deferred** | ⏭ |
| **ComfyUI txt2img / txt2vid** | `server.py:1369–1409` | none — requires ComfyUI running; **deferred** | ⏭ |
| **Admin surface (licensing / tenants / invoices / invites)** | `dialekt-cloud/src/dialekt_cloud/routers/admin.py` + `auth.py` | `role_admin.test_01` through `test_09` | ✅ |
| **Invite flow (cross-tenant isolation)** | `dialekt-cloud/src/dialekt_cloud/routers/auth.py:165–254` | `role_admin.test_04` (positive), `role_admin.test_05` (negative) | ✅ |

**Legend:** ✅ covered · ⚠ partial · ⏭ deferred · ❌ gap

## Summary

- **7 tools fully covered** (PG/MySQL/CH SQL at REST, schema reload, connection test, schema RAG, admin surface, invite isolation)
- **3 tools partially covered** (Python / shell / filesystem — publish-level yes, chat-level skipped pending UF-1 resolution)
- **5 tools deferred** to Milestone 2 per the original plan §6 (few-shot memory, HTTP, browser, screen capture, ComfyUI)

The headline gap is **finding UF-1**: chat-level SQL scenarios can't run
under TestClient because `DialektSQL` dispatches to
`DIALEKT_API=http://localhost:8765` — a real server process, not the
in-memory test app. See `MULTI_ROLE_E2E_REPORT.md` for the recommended
remediation (same shape as the R1 `DIALEKT_BACKEND_URL` fix — extend
the env indirection to `dialekt/llm/sql_language.py`).
