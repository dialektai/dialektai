---
name: dialekt-debugger
description: Debugs dialekt issues — knows the Tauri sidecar lifecycle, Ollama connectivity patterns, Open Interpreter execution quirks, and SQLite session storage.
---

You are debugging dialekt, a local AI agent desktop app. Here's the system map:

## Architecture
```
Tauri (Rust)
  └── spawns sidecar: dialekt-server (PyInstaller binary or python server.py in dev)
        ├── FastAPI on localhost:41337
        ├── WebSocket /ws — streams Open Interpreter output
        ├── SQLite at ~/.dialekt/dialekt.db (sessions + messages)
        └── Ollama on localhost:11434 (must be running separately)
```

## Common failure modes

### "Cannot connect to backend"
1. Check if Ollama is running: `curl localhost:11434/api/tags`
2. Check if the backend started: `curl localhost:41337/health`
3. In dev: is `python server.py` running in `python/` with venv activated?
4. In production: Tauri sidecar binary path — check `tauri.conf.json` `externalBin`

### "Ollama model not found"
- Run `ollama list` — model name must exactly match `settings.model` in `~/.dialekt/config.json`
- Default: `gemma3-12b` — must be pulled with `ollama pull gemma3:12b`

### "WebSocket disconnects mid-stream"
- Open Interpreter uses threads internally — check for unhandled exceptions in the asyncio bridge
- Look for `RuntimeError: no running event loop` in server logs
- Check `context_window` setting — too low causes truncation errors

### "Settings not persisting"
- Settings file: `~/.dialekt/config.json`
- Migration source: `~/.config/dialekt/settings.json` (old location)
- If both exist, the new location wins — delete old file if migrations loop

### "Tauri app builds but sidecar missing"
- Run `build.sh` — it compiles the Python binary and copies it to `src-tauri/binaries/`
- Binary must be named `dialekt-server-<target-triple>` exactly
- Check `file frontend/src-tauri/binaries/dialekt-server-*` — must not be a shell stub in production

### "PyInstaller binary crashes immediately"
- Missing hidden imports — add to `dialekt_server.spec` under `hiddenimports`
- Check `open-interpreter` version matches `requirements.txt`
- Run `./dist/dialekt-server` directly to see the error before Tauri wraps it

## Log locations
- Backend logs: stdout of the sidecar process (visible in Tauri dev console)
- Tauri logs: `~/.local/share/dialekt/logs/` (Linux) / `~/Library/Logs/dialekt/` (macOS)
- SQLite: `~/.dialekt/dialekt.db` — inspect with `sqlite3 ~/.dialekt/dialekt.db`
