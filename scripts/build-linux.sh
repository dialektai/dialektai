#!/usr/bin/env bash
# Build the full Linux distribution (.deb + AppImage) for dialekt.
#
# Usage:
#   scripts/build-linux.sh                    # full build
#   scripts/build-linux.sh --skip-sidecar     # reuse existing sidecar
#   scripts/build-linux.sh --skip-frontend    # reuse existing dist/
#
# Outputs (into dist/):
#   dist/dialekt_<version>_amd64.deb
#   dist/dialekt_<version>_amd64.AppImage
#
# Prerequisites on the build host (one-time):
#   - Rust toolchain + cargo-tauri (via `cargo install tauri-cli --version ^2`)
#   - Node.js 20+ + npm
#   - Docker (for the sidecar GLIBC-baseline build)
#   - System libs: libgtk-3-dev, libwebkit2gtk-4.1-dev, libssl-dev,
#                  libayatana-appindicator3-dev, librsvg2-dev
#
# CI note: this script is invoked by .github/workflows/release.yml — keep it
# self-contained and idempotent.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO"

SKIP_SIDECAR=0
SKIP_FRONTEND=0
for arg in "$@"; do
    case "$arg" in
        --skip-sidecar) SKIP_SIDECAR=1 ;;
        --skip-frontend) SKIP_FRONTEND=1 ;;
        -h|--help) grep '^# ' "$0" | sed 's/^# \?//'; exit 0 ;;
    esac
done

VERSION="$(grep -oP '"version":\s*"\K[0-9.]+' frontend/src-tauri/tauri.conf.json | head -1)"
echo "═══ dialekt Linux build · v$VERSION ═══"

# ── 1. sidecar (Python backend → single binary) ───────────────────────────────
if [[ $SKIP_SIDECAR -eq 0 ]]; then
    echo
    echo "▶ [1/4] building Python sidecar (Docker Ubuntu 22.04 GLIBC baseline)"
    (cd python && ./build_sidecar.sh)
else
    echo "▶ [1/4] skipping sidecar build (--skip-sidecar)"
    TRIPLE="x86_64-unknown-linux-gnu"
    if [[ ! -f "frontend/src-tauri/binaries/dialekt-server-$TRIPLE" ]]; then
        echo "  ✗ no sidecar at frontend/src-tauri/binaries/dialekt-server-$TRIPLE; drop --skip-sidecar"
        exit 2
    fi
fi

# ── 2. frontend (Vite React bundle) ──────────────────────────────────────────
if [[ $SKIP_FRONTEND -eq 0 ]]; then
    echo
    echo "▶ [2/4] building frontend bundle"
    cd "$REPO/frontend"
    npm ci --silent
    npm run build
    cd "$REPO"
else
    echo "▶ [2/4] skipping frontend build (--skip-frontend)"
fi

# ── 3. Tauri bundle (deb + AppImage) ─────────────────────────────────────────
echo
echo "▶ [3/4] tauri build (linux/deb + linux/appimage)"
cd "$REPO/frontend"
TAURI_BIN=""
if [[ -x ./node_modules/.bin/tauri ]]; then
    TAURI_BIN="./node_modules/.bin/tauri"
elif command -v cargo-tauri >/dev/null 2>&1; then
    TAURI_BIN="cargo tauri"
elif cargo tauri --version >/dev/null 2>&1; then
    TAURI_BIN="cargo tauri"
else
    echo "  ✗ tauri CLI not found. Install either:"
    echo "      cd frontend && npm install    # bundles @tauri-apps/cli locally"
    echo "      cargo install tauri-cli --version '^2' --locked"
    exit 3
fi
echo "  using: $TAURI_BIN"
$TAURI_BIN build --bundles deb appimage

# ── 4. collect artifacts ─────────────────────────────────────────────────────
cd "$REPO"
mkdir -p dist
DEB_SRC="$(find frontend/src-tauri/target/release/bundle/deb -name '*.deb' -printf '%T@ %p\n' 2>/dev/null | sort -nr | head -1 | cut -d' ' -f2-)"
APP_SRC="$(find frontend/src-tauri/target/release/bundle/appimage -name '*.AppImage' -printf '%T@ %p\n' 2>/dev/null | sort -nr | head -1 | cut -d' ' -f2-)"

[[ -n "$DEB_SRC" ]] && cp -v "$DEB_SRC" "dist/dialekt_${VERSION}_amd64.deb" || echo "  ⚠ no .deb produced"
[[ -n "$APP_SRC" ]] && cp -v "$APP_SRC" "dist/dialekt_${VERSION}_amd64.AppImage" || echo "  ⚠ no .AppImage produced"

# SHA256 sidecar files for Release integrity
echo
echo "▶ [4/4] artifacts in dist/:"
cd dist
for f in *.deb *.AppImage; do
    [[ -f "$f" ]] || continue
    sha256sum "$f" > "${f}.sha256"
    stat -c '  %s bytes  %n' "$f"
    echo "  sha256: $(cat "${f}.sha256" | cut -d' ' -f1)"
done
cd "$REPO"

echo
echo "✅ build complete · dist/dialekt_${VERSION}_amd64.{deb,AppImage}"
