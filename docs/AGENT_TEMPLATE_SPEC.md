# Agent Library — Template Specification

**Status:** v1 shipped
**Audience:** engineers + curators
**Last updated:** 2026-04-27

## What this document defines

The data shape, storage layout, and curation rules for entries in the
public Agent Library. Distinct from `dialekt.metadata.spec_version`
(the manifest contract used by the runtime) — this spec layers
**catalog metadata** on top of an existing manifest YAML.

## Architecture (v1)

```
   ┌───────────────────────┐         ┌───────────────────────┐
   │  dialekt-cloud (PG)   │  fetch  │  desktop sidecar      │
   │                       │ ◄─────  │  (FastAPI + SQLite)   │
   │  library_entries      │  HTTPS  │  library_templates    │
   │  ─────────────────    │         │  ─────────────────    │
   │  source of truth      │         │  cached mirror        │
   │  served at:           │         │  served at:           │
   │  /public/library      │         │  /library             │
   └─────────▲─────────────┘         └─────────▲─────────────┘
             │                                  │
             │  PR + redeploy                   │  POST /library/sync
             │                                  │
   ┌─────────┴─────────────┐         ┌─────────┴─────────────┐
   │  library_seed.py      │         │  Library screen       │
   │  (LIBRARY_TEMPLATES)  │         │  (LibraryScreen.jsx)  │
   └───────────────────────┘         └───────────────────────┘
```

- **Cloud is source of truth.** `dialekt-cloud/services/library_seed.py`
  defines `LIBRARY_TEMPLATES` — a tuple of `LibraryTemplate` dataclasses.
  Cloud lifespan startup upserts them idempotently into
  `library_entries` (PostgreSQL).
- **Cloud serves a public unauthenticated catalog** at
  `GET /public/library` and `GET /public/library/{id}`. Rate-limited at
  the edge (Cloudflare WAF), not in-process.
- **Desktop pulls and caches.** `POST /library/sync` fetches from
  cloud, upserts into the local SQLite `library_templates` table.
  `GET /library` reads from the local cache only — works offline as
  long as one sync has succeeded.
- **Install** copies the manifest YAML into the user's `agents` table
  via the shared `import_manifest_yaml()` service. The created agent
  gets a non-null `source_template_id` so the UI can offer
  "Update available" when the library entry's version bumps.

## Schema

### `library_entries` (cloud, PostgreSQL)

```sql
CREATE TABLE library_entries (
    id TEXT PRIMARY KEY,             -- stable slug, e.g. "sql-analyst-postgres"
    manifest_yaml TEXT NOT NULL,
    category TEXT NOT NULL,
    tags JSONB NOT NULL DEFAULT '[]',
    requires_connection BOOLEAN NOT NULL DEFAULT FALSE,
    requires_mcp BOOLEAN NOT NULL DEFAULT FALSE,
    signature TEXT,                  -- HMAC-SHA256 of manifest_yaml
    version TEXT NOT NULL DEFAULT '1.0.0',
    published BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

### `library_templates` (desktop, SQLite)

Same shape, denormalised `name` + `description` cached for cheap
listing (in-process YAML parse on every request was needlessly
repetitive once we moved to a list view that always shows them).

```sql
CREATE TABLE library_templates (
    id                  TEXT PRIMARY KEY,
    manifest_yaml       TEXT NOT NULL,
    name                TEXT NOT NULL,
    description         TEXT NOT NULL DEFAULT '',
    category            TEXT NOT NULL,
    tags                TEXT NOT NULL DEFAULT '[]',  -- JSON array
    requires_connection INTEGER NOT NULL DEFAULT 0,
    requires_mcp        INTEGER NOT NULL DEFAULT 0,
    version             TEXT NOT NULL DEFAULT '1.0.0',
    signature           TEXT,
    cached_at           TEXT NOT NULL DEFAULT (datetime('now'))
);
```

### `agents` extension

```sql
ALTER TABLE agents ADD COLUMN source_template_id TEXT;
```

NULL = user-authored. Non-NULL = installed from the library at the
referenced template's version-at-the-time. The agent stays independent
after install — we never auto-mirror manifest changes from library
back into the installed copy (forking semantics).

## Curation surface

What a curator decides per entry:

| Field | Source | Notes |
|---|---|---|
| `id` | curator | stable slug, kebab-case, namespaced if needed |
| `manifest_yaml` | curator | conforms to `dialekt-manifest` spec_version 1.1.0+ |
| `category` | curator | controlled vocabulary: `data-analytics` / `development` / `documents` / `other` |
| `tags` | curator | free-form array; used by the search filter |
| `version` | curator | semver; bumping triggers "Update available" UX |
| `requires_connection` | derived | computed from manifest at seed time (presence of `connections.required[]`) |
| `requires_mcp` | derived | computed from manifest at seed time (presence of `mcp_servers` / `mcp_tools` capability group) |
| `signature` | system | HMAC-SHA256 of `manifest_yaml` using `DIALEKT_LIBRARY_HMAC_SECRET` env. Reserved column for v2 desktop-side cache integrity verification. NULL in dev. |
| `published` | curator | soft-hide without deletion |

### Fields explicitly **not** in the schema (and why)

- **`pilot_source`** — leaks who's piloting the product. Even
  internally, we never want to ship "from IBA pilot" in the catalog.
  If we need attribution, do it in a private CRM, not in the public
  catalog.
- **`verified`** — needs a governance pipeline (who flips the flag,
  on what evidence). In v1 every entry from the curated seed is
  implicitly verified; the column's information value is zero until
  user-submitted templates exist.
- **`installed_count`** — would require telemetry. dialekt is
  local-first; counting installs centrally would break that promise.
  Showing fake counts is anti-trust. Defer until opt-in telemetry
  is a separate, explicit decision.
- **`subcategory`** — premature taxonomy. Use `tags` until the
  catalog grows past ~25 entries and search hits the wall.
- **`complexity`, `setup_time_minutes`** — subjective and
  unmaintained-as-soon-as-you-edit-the-manifest. If we need labels,
  derive them at render time from manifest signals (capabilities count
  + requires_connection → "5 min" / "15 min").

These are not "TODO for v2" items. They are **rejected by design**
unless a real owner + data source emerges later.

## API contract

### `GET /public/library` (cloud, unauthenticated)

```
GET /public/library?category=data-analytics&requires_connection=false&search=sql
→ 200 {
    "entries": [
      {
        "id": "sql-analyst-postgres",
        "name": "SQL Analyst (PostgreSQL)",
        "description": "Read-only PostgreSQL SQL assistant. Shows queries before executing.",
        "language": "multi",
        "category": "data-analytics",
        "tags": ["sql", "postgresql", "analytics"],
        "requires_connection": true,
        "requires_mcp": false,
        "version": "1.0.0",
        "signature": "...",
        "updated_at": "2026-04-27T08:00:00Z"
      },
      ...
    ]
  }
```

### `GET /public/library/{id}` (cloud, unauthenticated)

Same shape, plus `manifest_yaml`. Called by the desktop sync to fetch
each full entry; called by external integrations that want to inspect
a single template before committing.

### `GET /library` (desktop)

Same query interface as the cloud variant, served from the local
SQLite cache. Filters apply in SQL where cheap; substring search
applies in Python after row fetch.

### `POST /library/sync` (desktop)

Fetches from `{cloud_api_url}/public/library`, upserts into
`library_templates`. Idempotent. Called automatically on app boot when
online; user-triggered via a "Refresh library" button.

### `POST /library/{id}/install` (desktop)

Creates an agent from the cached template via the shared
`import_manifest_yaml()` service. Sets `agents.source_template_id`.
Returns 201 with `{ id, name, warnings }`.

## Lifecycle

```
new template:
  edit LIBRARY_TEMPLATES in dialekt-cloud/.../library_seed.py
  → PR + review (curation gate)
  → merge → cloud redeploy
  → next desktop boot pulls it via /library/sync
  → user sees the new card

template update (version bump):
  bump `version` field on the LibraryTemplate
  → same flow as above
  → desktop sees the new version on next sync
  → for already-installed agents (source_template_id matches),
    the Library screen shows "Update available" badge (v2)
```

## Out of scope for v1

- Submit-your-own-template UI (cloud admin moderation flow)
- Template usage analytics
- Per-template VRAM filter (uses `model.requirements.min_vram_gb` but
  not surfaced as a filter yet)
- "Install bundle" — pre-selected sets ("Education starter pack")
- Update-available banner on installed agents whose source bumped

These are P2 items in the architectural review. They're listed in
`/docs/AGENT_LIBRARY_FUTURE.md` (TODO) when prioritised.
