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

### Steps

1. Quit the dialekt desktop app.
2. Stop the background server:
   ```bash
   pkill -f "python3 .*server\.py"
   ```
   Or, if you run it under pm2 / systemd, use the relevant stop command.
3. Upgrade the package:
   ```bash
   pip install --upgrade dialekt-manifest-validator
   ```
4. Relaunch dialekt desktop. The server starts fresh and picks up the
   new schema.

### Why

Python caches imported modules in `sys.modules` for the life of the
interpreter process. `dialekt_manifest.schema` is imported once when
`server.py` boots; after that, updating the file on disk has no
effect until you restart.

### How to verify the upgrade took

```bash
# after restart
curl -s http://localhost:8765/about   # no direct schema version endpoint yet
pip show dialekt-manifest-validator | grep Version
```

Then Publish an agent that uses a value only the new schema accepts
(e.g. autonomy `"manual"` in 0.2.0). A 201 confirms the new schema is live.

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

## Future: `POST /admin/reload-schema` (planned, not shipped)

Nice-to-have: a button in Settings → Admin that reloads
`dialekt_manifest` in place, so pip-upgrading the validator no longer
requires a server restart. Deferred to Milestone 2 — the manual
restart takes 5 seconds and restarts are rare.

When this ships, the steps above collapse to:

```bash
pip install --upgrade dialekt-manifest-validator
# click "Reload validation schema" in Settings → Admin
```
