#!/usr/bin/env bash
# Build the dialekt Python backend as a single-file binary for Tauri
# packaging.
#
# Usage:
#   cd python
#   ./build_sidecar.sh                 # auto-detects GLIBC baseline
#   DIALEKT_SIDECAR_TARGET=x86_64-unknown-linux-gnu ./build_sidecar.sh
#   DIALEKT_BUILD_MODE=docker ./build_sidecar.sh      # force docker build
#   DIALEKT_BUILD_MODE=native ./build_sidecar.sh      # force native build
#
# Output:
#   python/dist/dialekt-server                             (raw binary)
#   frontend/src-tauri/binaries/dialekt-server-<target>    (Tauri sidecar name)
#
# GLIBC compatibility:
#   PyInstaller binaries are dynamically linked. To run on Ubuntu 22.04+
#   / Debian 12+ we must build on Ubuntu 22.04 (GLIBC 2.35). The script
#   detects the host GLIBC and switches to Docker build if the host is
#   newer — no manual flag required for the common case.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ── decide: native or docker build? ───────────────────────────────────────────
# Baseline: Ubuntu 22.04 ships GLIBC 2.35. Newer hosts will produce binaries
# that refuse to run on 22.04 with "version GLIBC_2.38 not found". Detect
# the host GLIBC and fall through to a Docker build when it's too new.
detect_glibc() {
    ldd --version 2>/dev/null | head -1 | grep -oE '[0-9]+\.[0-9]+$' | head -1
}
HOST_GLIBC="$(detect_glibc)"
MODE="${DIALEKT_BUILD_MODE:-}"

if [[ -z "$MODE" ]]; then
    if [[ -n "$HOST_GLIBC" ]] && [[ "$(printf '%s\n' "2.35" "$HOST_GLIBC" | sort -V | tail -1)" == "2.35" ]]; then
        MODE="native"
    else
        MODE="docker"
    fi
fi

echo "ℹ  host GLIBC=$HOST_GLIBC → build mode: $MODE"

if [[ "$MODE" == "docker" ]]; then
    # Re-entrant: build the builder image (once), then run this script inside
    # it with DIALEKT_BUILD_MODE=native so the GLIBC check passes.
    echo "ℹ  host GLIBC is newer than Ubuntu 22.04 baseline; building in Docker..."
    if ! docker image inspect dialekt-sidecar-builder >/dev/null 2>&1; then
        echo "ℹ  building dialekt-sidecar-builder image (first run, ~5 min)..."
        docker build -f "$SCRIPT_DIR/Dockerfile.build" -t dialekt-sidecar-builder "$SCRIPT_DIR"
    fi
    exec docker run --rm \
        -e DIALEKT_BUILD_MODE=native \
        -e "DIALEKT_SIDECAR_TARGET=${DIALEKT_SIDECAR_TARGET:-}" \
        -v "$SCRIPT_DIR/..":/src \
        -w /src/python \
        dialekt-sidecar-builder \
        bash build_sidecar.sh
fi

# ── detect target triple ──────────────────────────────────────────────────────
# Tauri expects binaries named dialekt-server-<rust-target-triple>.
detect_triple() {
    local host_arch host_os
    host_arch="$(uname -m)"
    host_os="$(uname -s | tr '[:upper:]' '[:lower:]')"
    case "$host_os:$host_arch" in
        linux:x86_64)  echo "x86_64-unknown-linux-gnu" ;;
        linux:aarch64) echo "aarch64-unknown-linux-gnu" ;;
        darwin:x86_64) echo "x86_64-apple-darwin" ;;
        darwin:arm64)  echo "aarch64-apple-darwin" ;;
        mingw*:x86_64|msys*:x86_64|cygwin*:x86_64) echo "x86_64-pc-windows-msvc" ;;
        *) echo "UNKNOWN:$host_os:$host_arch" ;;
    esac
}
TARGET="${DIALEKT_SIDECAR_TARGET:-$(detect_triple)}"
if [[ "$TARGET" == UNKNOWN:* ]]; then
    echo "❌ Cannot detect Rust target triple for this host; set DIALEKT_SIDECAR_TARGET." >&2
    exit 1
fi

# ── venv setup ────────────────────────────────────────────────────────────────
if [[ ! -d venv ]]; then
    echo "ℹ  creating venv..."
    python3 -m venv venv
fi
# shellcheck disable=SC1091
source venv/bin/activate

echo "ℹ  ensuring build deps..."
pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt
pip install --quiet 'pyinstaller>=6.0.0'

# ── build ─────────────────────────────────────────────────────────────────────
echo "ℹ  running pyinstaller..."
rm -rf build dist
pyinstaller --clean --log-level=WARN dialekt_server.spec

if [[ ! -f dist/dialekt-server ]]; then
    echo "❌ PyInstaller produced no dist/dialekt-server — check logs." >&2
    exit 2
fi

BIN_SIZE_MB="$(du -m dist/dialekt-server | cut -f1)"
echo "✅ built dist/dialekt-server ($BIN_SIZE_MB MB)"

# ── install into Tauri sidecar path ───────────────────────────────────────────
TAURI_BIN_DIR="$SCRIPT_DIR/../frontend/src-tauri/binaries"
mkdir -p "$TAURI_BIN_DIR"
TAURI_PATH="$TAURI_BIN_DIR/dialekt-server-$TARGET"
cp dist/dialekt-server "$TAURI_PATH"
chmod +x "$TAURI_PATH"
echo "✅ installed → $TAURI_PATH"

# ── smoke test ────────────────────────────────────────────────────────────────
# Skip in CI / non-interactive environments where Ollama / DB deps aren't up —
# the sidecar's lifespan tries to reach Ollama and can hang on retry backoffs.
# Set DIALEKT_SKIP_SMOKE=1 to bypass the startup test. Binary presence is
# already verified by the build step ("built dist/dialekt-server"); smoke is
# just a dev-convenience check.
if [[ "${DIALEKT_SKIP_SMOKE:-0}" == "1" ]]; then
    echo "ℹ  smoke test skipped (DIALEKT_SKIP_SMOKE=1)"
else
    echo "ℹ  smoke-testing binary (starts + responds to /health)..."
    "$TAURI_PATH" --help >/dev/null 2>&1 || true  # may not support --help, that's OK

    # Quick boot check: start the server on a free port, curl /health, kill it.
    PORT="${DIALEKT_SIDECAR_SMOKE_PORT:-18765}"
    DIALEKT_PORT="$PORT" "$TAURI_PATH" &
    PID=$!
    # Give uvicorn up to 15s to come up.
    OK=""
    for i in $(seq 1 15); do
        sleep 1
        if curl -sf "http://127.0.0.1:$PORT/health" >/dev/null 2>&1; then
            OK=1
            echo "✅ /health OK on port $PORT after ${i}s"
            break
        fi
    done
    kill "$PID" 2>/dev/null || true
    # Force-kill after a short grace so `wait` can't block forever on a
    # sidecar that's stuck in lifespan (e.g. Ollama retry backoff).
    ( sleep 5; kill -KILL "$PID" 2>/dev/null || true ) &
    wait "$PID" 2>/dev/null || true

    if [[ -z "$OK" ]]; then
        echo "⚠  smoke test failed — binary built but /health did not respond on :$PORT." >&2
        echo "    Check with:  $TAURI_PATH" >&2
        exit 3
    fi
fi

echo
echo "✅ sidecar ready: $TAURI_PATH"
echo "   size: $BIN_SIZE_MB MB"
echo "   target: $TARGET"
