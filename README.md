# dialekt.ai

A local AI agent for your desktop — runs entirely on your machine, executes code, manages files, and controls your OS via natural language.

Built with **Tauri + React** (frontend) and **FastAPI + Open Interpreter** (backend). Models run locally through **Ollama** — no cloud, no telemetry, no data leaving your computer.

---

## Features

- **Full computer access** — read/write files, run shell commands, open apps, browse the web
- **Local-first** — all inference via Ollama (Gemma 3, Llama 3, Mistral, etc.)
- **Image & video generation** — integrates with local ComfyUI (Flux Schnell, LTX-Video)
- **Persistent sessions** — chat history stored in SQLite under `~/.dialekt/`
- **Cross-platform** — Linux binaries shipping now; macOS and Windows builds planned for Q3 2026
- **Autonomy modes** — `ask-write` (confirms destructive actions) or `auto` (fully autonomous)

---

## Requirements

| Tool | Version |
|------|---------|
| [Ollama](https://ollama.com) | ≥ 0.3 |
| Python | ≥ 3.11 |
| Node.js | ≥ 20 |
| Rust + Cargo | stable |
| A model | e.g. `ollama pull gemma3:12b` |

---

## Quick Start

### 1. Pull a model

```sh
ollama pull gemma3:12b
```

### 2. Set up the Python backend

```sh
cd python
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 3. Configure Ollama model (optional)

Copy `Modelfile.example` to `Modelfile`, set the path to your GGUF file, then:

```sh
ollama create dialekt -f Modelfile
```

### 4. Run in development mode

```sh
# Terminal 1 — Python backend
cd python && source venv/bin/activate && python server.py

# Terminal 2 — Tauri dev
cd frontend && npm install && npm run tauri dev
```

---

## Building a Release

```sh
bash build.sh
```

This script:
1. Compiles the Python backend to a standalone binary via PyInstaller
2. Copies the binary as a Tauri sidecar
3. Runs `npm run tauri build` to produce platform installers

Output: `frontend/src-tauri/target/release/bundle/`

---

## Project Structure

```
dialekt/
├── python/                  # FastAPI backend
│   ├── server.py            # Main API server (WebSocket + REST)
│   ├── requirements.txt
│   ├── dialekt_server.spec  # PyInstaller build spec
│   └── tests/
├── frontend/                # Tauri + React app
│   ├── src/                 # React components & screens
│   └── src-tauri/           # Rust shell + Tauri config
├── landing/                 # Static marketing page
├── Modelfile.example        # Template for custom Ollama model
└── build.sh                 # Full release build script
```

---

## API (backend)

The backend runs on `localhost:41337` by default.

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Health check |
| `WS` | `/ws` | Streaming chat (Open Interpreter) |
| `POST` | `/ollama/start` | Pull/start an Ollama model |
| `GET` | `/sessions` | List chat sessions |
| `GET` | `/sessions/{id}/messages` | Get session history |
| `DELETE` | `/sessions/{id}` | Delete session |

---

## Agent Manifests

dialekt agents are defined as portable YAML files (`.agent.yaml`).

**Manifest format:** [AGENT_MANIFEST_SPEC.md](AGENT_MANIFEST_SPEC.md) — covers all fields, types, security rules, and examples.

**Validator:** [`dialekt-manifest-validator`](https://github.com/dialektai/dialekt-manifest-validator) — validate manifests before importing or publishing.

```bash
pip install "git+https://github.com/dialektai/dialekt-manifest-validator.git@v0.2.0"
dialekt-validate-manifest my-agent.agent.yaml
```

> Distributed via GitHub tags while the schema stabilises — see
> [`docs/SCHEMA_RELEASE.md`](docs/SCHEMA_RELEASE.md) for the release
> runbook and future PyPI migration path.

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). All contributors must sign off commits with the [Developer Certificate of Origin](https://developercertificate.org).

---

## License

[GNU Affero General Public License v3.0](LICENSE) — see LICENSE for details.

For commercial use without AGPL obligations, contact: hello@dias.now
