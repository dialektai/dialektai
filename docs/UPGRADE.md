# Upgrading dialekt

Short runbook for keeping a running dialekt install in sync when
dependencies change. Separate from `docs/RELEASE.md`, which is the
release-engineering side (cutting a new version, signing, publishing).

---

## Upgrading `dialekt-manifest-validator`

The schema package defines which values `AgentManifest` accepts
(autonomy levels, connection types, capability groups, etc.). Every
time it gains a new value the running dialekt-server process needs to
re-import it — pip only replaces files on disk, the interpreter still
holds the old constants in memory.

### Steps (recommended, no restart)

1. Upgrade the package while dialekt keeps running. The schema is
   distributed via GitHub tags (not PyPI — see `docs/SCHEMA_RELEASE.md`
   for the why), so install from a pinned tag:
   ```bash
   # Reinstall from latest supported tag (check docs/SCHEMA_RELEASE.md
   # for the current one; v0.2.0 is the minimum dialekt 0.8+ accepts)
   pip install --upgrade --force-reinstall \
     "git+https://github.com/dialektai/dialekt-manifest-validator.git@v0.2.0"
   ```
   To pin a specific version:
   ```bash
   pip install \
     "git+https://github.com/dialektai/dialekt-manifest-validator.git@v0.X.Y"
   ```
2. Open **Settings → Admin → Maintenance** and click **Reload validation schema**.
   A toast confirms the new version + autonomy-level count.

That's it — the running server re-imports the schema in place via
`POST /admin/reload-schema`. No process restart required.

### Steps (fallback, if the endpoint is unavailable)

For older builds (<0.2.x) that don't have the reload endpoint, or if
the button is unreachable, restart manually:

1. Quit the dialekt desktop app.
2. Stop the background server:
   ```bash
   pkill -f "python3 .*server\.py"
   ```
   Or, if you run it under pm2 / systemd, use the relevant stop command.
3. Upgrade the package:
   ```bash
   pip install --upgrade --force-reinstall \
     "git+https://github.com/dialektai/dialekt-manifest-validator.git@v0.2.0"
   ```
4. Relaunch dialekt desktop. The server starts fresh and picks up the
   new schema.

### Why this is needed at all

Python caches imported modules in `sys.modules` for the life of the
interpreter process. `dialekt_manifest.schema` is imported once when
`server.py` boots; after that, updating the file on disk has no
effect until the module is re-imported (either via the reload
endpoint, or by restarting the process).

### How to verify the upgrade took

```bash
# confirm the new version is live in-process
curl -s -X POST http://localhost:8765/admin/reload-schema | jq '.package_version, .constants.autonomy_levels'
pip show dialekt-manifest-validator | grep Version
```

The values must match. Then Publish an agent that uses a value only
the new schema accepts (e.g. autonomy `"manual"` in 0.2.0). A 201
confirms the new schema is live.

### Symptoms if you forget to restart

Publish fails with a 422 that lists **the old** allowed values in the
error message — for example after 0.1.0 → 0.2.0, a manifest with
`autonomy.recommended: "manual"` is rejected with:

```
Autonomy level must be one of ['review-only', 'ask-before-write',
'autonomous', 'sandbox-only']
```

…which is the 0.1.0 list, not 0.2.0's five-value list. The error copy
is misleading but the fix is always just: restart the server.

---

## Upgrading Ollama models

Agents reference models by tag (e.g. `qwen2.5-coder:7b`). If you
`ollama pull` a newer weights build but keep the same tag, dialekt
will pick it up on the next chat turn — no restart needed. If you
pull a **new** tag the agent declares in its manifest, new sessions
will find it via `pick_model_for_agent` automatically.

---

## Upgrading the dialekt desktop app itself

See `docs/RELEASE.md` for the end-to-end CI + Tauri signing flow. For
a user on an installed build: the in-app updater (Tauri updater)
handles this without manual steps.

---

## Running on a non-default port

By default dialekt-server binds to port 8765. As of 2026-04-24,
internal self-calls from LLM plugins (DialektSQL, retry loop) go
through an in-process ASGI dispatch rather than an HTTP roundtrip,
so **the port doesn't matter for the built-in plugins** — you can
set `DIALEKT_PORT=8766` and everything just works.

The `DIALEKT_BACKEND_URL` env var is still honoured for **detached**
callers (a subprocess worker, a CLI tool, a third-party script that
imports `dialekt.llm.*` outside the server process):

```bash
# Only needed for detached plugin callers — not for dialekt-server itself
export DIALEKT_BACKEND_URL=http://localhost:8766
```

When you launch `server.py` directly via `python3`, the env is
auto-populated from `DIALEKT_HOST` / `DIALEKT_PORT` at startup as a
convenience for such external tooling.

See `docs/PLUGIN_ARCHITECTURE.md` for the full `PluginContext` design
and how to add new plugins that automatically inherit the same
in-process-vs-http transport switch.

---

## `POST /admin/reload-schema` (shipped)

Reloads `dialekt_manifest` in place via `importlib.reload` on the
server process, so pip-upgrading the validator no longer requires a
restart. The Settings → Admin → Maintenance → **Reload validation
schema** button calls this endpoint and surfaces the new constants
in a toast.

Response shape:

```json
{
  "ok": true,
  "reloaded": ["dialekt_manifest.schema", "dialekt_manifest.validator", ...],
  "errors": [],
  "package_version": "0.2.1",
  "constants": {
    "autonomy_levels": [...],
    "capability_groups": [...],
    "connection_types": [...],
    "supported_spec_versions": [...]
  }
}
```

The endpoint only reloads the schema module and its dependents —
it does **not** touch the Open Interpreter runtime, active agents,
or running chat sessions.
