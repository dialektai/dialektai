# Settings Coverage — Multi-Role E2E 2026-04-24

Settings pages in `frontend/src/screens/SettingsScreen.jsx` and how
the 2026-04-24 multi-role sweep exercises each one.

| Page | Line range | What user can do | Covered by | Status |
|---|---|---|---|---|
| **Models** | 542–696 | Pick active model, pull new, adjust knobs | `role_developer.test_15` (settings blob); default model seeded in `role_user` fixture | ✅ blob round-trip<br>⏭ per-model pull not tested (requires Ollama pull bandwidth) |
| **Personality** | 701–771 | Tone / verbosity / prompt | `role_developer.test_15` (POST /settings) | ✅ via blob |
| **Appearance** | 776–846 | Theme / fonts / sidebar width | `role_developer.test_15` | ✅ via blob |
| **Shortcuts** | 851–897 | **View only — no user change** | n/a | ✅ display-only, nothing to persist |
| **Permissions** | 504–537 | Autonomy + allow-lists | `role_developer.test_15` | ✅ via blob |
| **Filesystem** | 902–946 | Access rules | `role_developer.test_15` | ✅ via blob |
| **Terminal & shell** | 951–1035 | Env vars + allow-list + sudo | `role_developer.test_15` | ✅ via blob |
| **Browser** | 1036–1068 | Headless / cookies | — | ⏭ placeholder (`v1.1`) |
| **Screen control** | 1073–1113 | Capture config | — | ⏭ placeholder (`v1.1`) |
| **MCP tools** | 1127–1145 | Tool list | — | ⏭ placeholder (`v1.1`) |
| **Connections** | 1477–1845 | Add/edit/test/reindex PG/MySQL/CH | `role_developer.test_01/02/03` (CRUD), `test_13` (negative), `test_14` (reindex) | ✅ |
| **Agents** | 1891–2097 | Bind connections to agents | `role_developer.test_04` (bind), `test_05` (no binding), `test_06` (mysql bind), `test_11` (delete CASCADE), `role_user.test_06` (empty state) | ✅ |
| **Storage & memory** | 1150–1295 | Facts + export + wipe | `role_developer.test_16` (wipe) | ✅ wipe covered<br>⏭ facts CRUD not tested |
| **Performance** | 1300–1349 | LLM knobs | `role_developer.test_15` | ✅ via blob |
| **Privacy & telemetry** | 1354–1404 | Toggles | `role_developer.test_15` | ✅ via blob |
| **Admin** | 2102–2228 | Stats + reload schema + wipe | `role_developer.test_12` (reload), `test_16` (wipe); overnight suite for /admin/stats | ✅ |
| **About** | 1409–1463 | License list / build info | — | ⏭ display-only; GET /about hit indirectly by `role_developer` fixture boot |

**Legend:** ✅ covered · ⚠ partial · ⏭ placeholder or deferred

## Summary

- **12 pages covered** (including all 7 UI-only blob-persisted pages via the shared `POST /settings` round-trip test)
- **3 pages are placeholders** for v1.1 (Browser, Screen control, MCP tools)
- **1 display-only page** (Shortcuts) — no persistence to cover
- **1 display-only page** (About) — `/about` endpoint hit as a side-effect of the server fixture boot

## Notes on the blob model

The 7 "UI-only" pages (Personality, Appearance, Permissions, Filesystem,
Terminal & shell, Performance, Privacy & telemetry) all serialize their
state through a single `POST /settings` → `GET /settings` round-trip
— so one test (`role_developer.test_15`) covers the persistence
guarantee for all seven. Per-field coverage is intentionally not
worth the maintenance cost: any regression in the blob endpoint
would fail the same single test.

## Gaps worth considering for M2

1. **Facts CRUD** in Storage & memory — user-facing feature, would
   benefit from a dedicated test.
2. **Ollama model pull streaming** (`/ollama/pull/stream`) — currently
   not exercised anywhere.
3. **Cloud Sync / License UI** (Admin → Cloud Sync card) — endpoints
   exist (`/license/*`, `/sync/*`) but are not covered.
