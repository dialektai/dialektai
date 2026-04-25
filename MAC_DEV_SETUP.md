# Mac dev setup — dialekt desktop

## Prerequisites

```bash
# Homebrew if you don't have it
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# Tooling
brew install python@3.12 node@22 rust ollama
brew install --cask github            # only if you want gh cli
xcode-select --install                # Xcode CLT for Rust/Tauri linking

# Node 22 via Homebrew (or use nvm if you prefer)
brew link --overwrite node@22

# Pull at least one Ollama model (this is what dialekt asks for first)
ollama serve &                         # leave it running in another terminal
ollama pull gemma3-12b                 # or qwen2.5-coder:7b for tool-calling
```

## Clone + install

```bash
git clone https://github.com/dialektai/dialektai.git ~/dev/dialekt
cd ~/dev/dialekt

# Python backend
cd python
python3.12 -m venv venv
source venv/bin/activate
pip install --upgrade pip wheel
pip install -r requirements.txt

# Frontend
cd ../frontend
npm install
```

## Run dev mode

Two terminals:

```bash
# T1: backend (FastAPI on :8765)
cd ~/dev/dialekt/python
source venv/bin/activate
python3 server.py

# T2: frontend dev server (Vite on :5173)
cd ~/dev/dialekt/frontend
npm run dev
# Or for the full Tauri shell:
npm run tauri dev
```

Open `http://localhost:5173` in any browser, or just launch the Tauri window.

## License (skip the trial signup)

When the License screen appears, paste:

```
dialekt_c2734199534a5d544ca338d50118c427310f378fcc5fe3cee91399bc05aa055f
```

(Saved separately — already activated against the cloud admin.)

## Notes (учитывая всё что мы сегодня нашли)

- **Ollama port 11434** must be reachable. If `ollama serve` isn't running, the
  desktop's diagnostic page will show backend offline.
- **Model name compatibility**: as of v0.26.1 the resolver auto-detects the
  literal Ollama tag, so both `gemma3-12b:latest` and `gemma3:12b` work.
- **Rust target on Mac**: Tauri build uses `aarch64-apple-darwin` by default
  (M1/M2/M3). For Intel Macs add `--target x86_64-apple-darwin` to `tauri build`.
- **macOS PATH caveat for github MCP**: GUI-launched Tauri inherits a stripped
  PATH that excludes `~/go/bin`. If the github MCP template fails with
  "command not found", either symlink the binary to `/usr/local/bin/` OR
  edit the template's `command` to use the absolute path.

## What lives where

```
dialekt/
├── python/             FastAPI backend (port 8765)
├── frontend/           React + Vite (port 5173 dev)
│   └── src-tauri/      Tauri shell (Rust, builds .dmg/.app)
├── docs/               Design docs + backlogs
├── dialekt-cloud/      Cloud admin (separate, NOT needed for desktop dev)
└── landing/            Marketing site (separate)
```

## No `.env` needed for desktop

The desktop app is fully self-contained — settings persist in
`~/.dialekt/config.json` and `~/.dialekt/secrets.enc`. There's nothing
machine-specific to copy from this Linux box; just clone, install, run.

If you want to copy your existing license + sessions from this machine
to the Mac, copy the entire `~/.dialekt/` directory. But the OS keychain
secrets won't transfer — Linux SecretService and macOS Keychain are
different stores; you'd need to re-enter any provider API keys / MCP
server credentials on the Mac.
