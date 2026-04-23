# Building dialekt for Linux

## TL;DR

Releases are built by `.github/workflows/release.yml` on GitHub Actions
`ubuntu-22.04` runners. **Don't distribute binaries built on a dev machine
newer than Ubuntu 22.04 — they will require a GLIBC that users don't
have.**

For a release:

```bash
# Tag and push
git tag v0.9.1
git push origin v0.9.1

# Workflow builds .deb + .AppImage, uploads to GitHub Release automatically
```

For local dev testing of the pipeline:

```bash
# Sidecar only (Docker ensures GLIBC compatibility)
cd python && ./build_sidecar.sh

# Full .deb + .AppImage (caveat: Rust binary will link against host GLIBC)
./scripts/build-linux.sh
```

---

## GLIBC baseline

`dialekt_0.9.0_amd64.deb` contains two executables:

| Binary | Built where | GLIBC target |
|---|---|---|
| `/usr/bin/dialekt` | Rust/Cargo (Tauri wrapper) | Build host's GLIBC |
| `/usr/bin/dialekt-server` | PyInstaller (Python sidecar) | Build host's GLIBC |

PyInstaller and Cargo both produce **dynamically linked** ELF binaries
whose runtime requires the build host's `libc` version. Running the
resulting binary on an older distro errors with:

```
libc.so.6: version `GLIBC_2.38' not found
```

Ubuntu 22.04 LTS ships GLIBC 2.35. That's our baseline. To produce a
`.deb`/`.AppImage` usable on Ubuntu 22.04+ / Debian 12+ / Fedora 38+,
**the whole build must happen on a GLIBC-2.35 host**.

Two ways to achieve that:

### 1. GitHub Actions (recommended)

The workflow uses `ubuntu-22.04` runners. Every tag push produces
official binaries. No dev action required.

### 2. Local Docker (for debugging)

The Python sidecar already goes through Docker automatically via
`python/Dockerfile.build` (Ubuntu 22.04 base). The Rust Tauri build
does **not** yet — it runs on the host. To force a full Docker build
locally:

```bash
docker run --rm \
  -v "$(pwd)":/src -w /src \
  mcr.microsoft.com/devcontainers/base:ubuntu-22.04 \
  bash -c '
    apt-get update &&
    apt-get install -y curl build-essential pkg-config nodejs npm \
      libwebkit2gtk-4.1-dev libgtk-3-dev libayatana-appindicator3-dev \
      librsvg2-dev libssl-dev python3.12 python3.12-venv &&
    curl --proto "=https" -sSf https://sh.rustup.rs | sh -s -- -y &&
    . $HOME/.cargo/env &&
    cd python && ./build_sidecar.sh && cd .. &&
    ./scripts/build-linux.sh --skip-sidecar
  '
```

This is ad-hoc and unvalidated on all CI paths — the authoritative
build is the one GitHub produces.

---

## Build pipeline overview

```
┌──────────────────────┐
│  python/server.py    │ FastAPI + uvicorn + open-interpreter + ...
│  python/dialekt/     │ llm wrapper, retry loop, few-shot memory
│  python/mcp_servers/ │ postgres/mysql/clickhouse connectors
└──────────┬───────────┘
           │
    PyInstaller (inside
    Docker Ubuntu 22.04)
           ▼
┌──────────────────────┐
│ dialekt-server       │ single-file binary, ~125 MB
│ (x86_64 ELF)         │
└──────────┬───────────┘
           │ copied to frontend/src-tauri/binaries/
           │     dialekt-server-x86_64-unknown-linux-gnu
           ▼
┌──────────────────────┐
│ Tauri bundle         │ Rust binary wraps React UI + spawns sidecar
│                      │ (tauri_plugin_shell::sidecar)
└──────────┬───────────┘
           │ npm run tauri -- build --bundles deb appimage
           ▼
┌──────────────────────┐
│ dialekt_X_amd64.deb  │ ~127 MB — direct install on Ubuntu/Debian
│ dialekt_X.AppImage   │ ~130 MB — universal
└──────────────────────┘
```

---

## Dependencies

Runtime (installed automatically by the `.deb`):

- `libwebkit2gtk-4.1-0` — WebKit engine for the app's UI
- `libgtk-3-0` — Window chrome
- `libayatana-appindicator3-1` — System tray
- `libssl3` — TLS (httpx + Python)

The Python sidecar itself has no runtime dependencies apart from the
GLIBC baseline — Python and every pip package is baked into the PyInstaller
binary.

Build-time (the CI runner / dev machine needs these to **produce** the .deb):

- Node.js 22, npm
- Rust stable (`rustup default stable`)
- Python 3.12
- PyInstaller ≥6.0
- Docker (for the sidecar GLIBC baseline build)
- System dev libs: `libwebkit2gtk-4.1-dev libgtk-3-dev libssl-dev libayatana-appindicator3-dev librsvg2-dev pkg-config build-essential`

The `.github/workflows/release.yml` job installs all of these on
`ubuntu-22.04` before building.

---

## Installing the `.deb` locally

```bash
# After downloading from a release:
curl -fsSLO https://github.com/dialektai/dialektai/releases/download/v0.9.0/dialekt_0.9.0_amd64.deb
sudo dpkg -i dialekt_0.9.0_amd64.deb
# If dpkg complains about missing dependencies:
sudo apt-get install -f

# Launch:
dialekt
# …or via the desktop menu entry (GNOME / KDE).
```

The Python sidecar starts automatically when the Tauri window opens —
it's spawned via `tauri_plugin_shell::sidecar` as a child process and
forwarded stdout/stderr.

---

## Uninstall

```bash
sudo apt-get remove dialekt
# User data at ~/.dialekt/ is kept — remove manually if you want a clean reinstall:
rm -rf ~/.dialekt
```

---

## Troubleshooting

### "version `GLIBC_2.38' not found"

The binary was built on a system newer than the target. Rebuild on
Ubuntu 22.04 (or download a CI-built release).

### "Failed to load Python shared library"

PyInstaller's bundled libpython.so was compiled against a newer glibc
than the target. Same fix as above.

### Sidecar doesn't start but `dialekt` window opens

The Tauri console logs the sidecar's stderr. Run from a terminal to see it:

```bash
/usr/bin/dialekt
# Look for [server] lines.
```

Test the sidecar directly:

```bash
DIALEKT_PORT=18900 /usr/bin/dialekt-server
# In another terminal:
curl http://127.0.0.1:18900/health
```

### WebKit errors on older GNOME

Install `libwebkit2gtk-4.1-0` (should be pulled by the `.deb` automatically).
On systems where only the older 4.0 series is packaged, the build won't
be compatible — use the AppImage instead.
