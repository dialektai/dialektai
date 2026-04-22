---
name: dev
description: Start dialekt in development mode — backend + Tauri frontend
---

Start the Python backend and Tauri dev server for local development.

## Steps

1. **Start the Python backend**

```bash
cd /home/dias/projects/desktop/dialekt/python
source venv/bin/activate
python server.py
```

Verify it's up: `curl localhost:41337/health` should return `{"status":"ok"}`.

2. **Start Tauri dev** (separate terminal)

```bash
cd /home/dias/projects/desktop/dialekt/frontend
npm run tauri dev
```

First run compiles Rust — takes ~3 minutes. Subsequent runs are fast.

3. **Verify Ollama is running**

```bash
curl localhost:11434/api/tags
```

If not: `ollama serve &` and pull the model: `ollama pull gemma3:12b`

## Run tests only

```bash
cd /home/dias/projects/desktop/dialekt/python
source venv/bin/activate
pytest tests/ -v
```
