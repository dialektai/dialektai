#!/usr/bin/env bash
# dialekt distribution build script
#
# Usage:
#   ./build.sh              — detect current platform, build all
#   ./build.sh macos        — macOS universal .dmg (requires macOS)
#   ./build.sh linux        — Linux .deb + .AppImage
#   ./build.sh windows      — Windows .msi (requires Windows or cross toolchain)
#   ./build.sh python-only  — only rebuild the Python sidecar
#   ./build.sh frontend-only — skip Python rebuild, just package Tauri
#
# Prerequisites:
#   Python venv in python/venv/ (or it will be created)
#   Rust + cargo (installed via rustup)
#   Node.js v18+ (via nvm)
#   For macOS: Xcode Command Line Tools
#   For Linux: build-essential, libwebkit2gtk-4.1-dev, libssl-dev
#   For Windows: MSVC build tools

set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
PYTHON_DIR="$ROOT/python"
TAURI_DIR="$ROOT/frontend"
BINARIES_DIR="$TAURI_DIR/src-tauri/binaries"

PLATFORM="${1:-auto}"
if [ "$PLATFORM" = "auto" ]; then
  case "$(uname -s)" in
    Darwin)  PLATFORM="macos"   ;;
    Linux)   PLATFORM="linux"   ;;
    MINGW*|CYGWIN*|MSYS*) PLATFORM="windows" ;;
    *)       PLATFORM="linux"   ;;
  esac
fi

# ── Target triple detection ───────────────────────────────────────────────────

get_target_triple() {
  case "$PLATFORM" in
    macos)   echo "universal-apple-darwin" ;;
    linux)   rustc -vV 2>/dev/null | grep ^host | cut -d' ' -f2 || echo "x86_64-unknown-linux-gnu" ;;
    windows) echo "x86_64-pc-windows-msvc" ;;
  esac
}

TARGET="$(get_target_triple)"

echo ""
echo "  dialekt build"
echo "  ─────────────────────────────────────"
echo "  Platform : $PLATFORM"
echo "  Target   : $TARGET"
echo ""

# ── Step 1: Python venv & dependencies ───────────────────────────────────────

if [ "$PLATFORM" != "frontend-only" ]; then
  echo "→ Setting up Python venv..."
  if [ ! -d "$PYTHON_DIR/venv" ]; then
    python3 -m venv "$PYTHON_DIR/venv"
  fi
  source "$PYTHON_DIR/venv/bin/activate"
  pip install --quiet -r "$PYTHON_DIR/requirements.txt"
  pip install --quiet pyinstaller
fi

# ── Step 2: Build Python sidecar with PyInstaller ────────────────────────────

if [ "$PLATFORM" != "frontend-only" ]; then
  echo "→ Building Python sidecar (PyInstaller)..."
  cd "$PYTHON_DIR"

  if [ "$PLATFORM" = "macos" ]; then
    # Build both architectures and lipo them into a universal binary
    pyinstaller dialekt_server.spec \
      --distpath dist \
      --target-arch arm64 \
      --noconfirm -y 2>/dev/null

    ARM_BINARY="$PYTHON_DIR/dist/dialekt-server"
    mv "$ARM_BINARY" "${ARM_BINARY}-arm64"

    pyinstaller dialekt_server.spec \
      --distpath dist \
      --target-arch x86_64 \
      --noconfirm -y 2>/dev/null

    X86_BINARY="$PYTHON_DIR/dist/dialekt-server"
    mv "$X86_BINARY" "${X86_BINARY}-x86_64"

    lipo -create -output "$PYTHON_DIR/dist/dialekt-server" \
      "${ARM_BINARY}-arm64" "${X86_BINARY}-x86_64"

    echo "  Universal binary created via lipo"
  else
    pyinstaller dialekt_server.spec \
      --distpath dist \
      --noconfirm -y 2>/dev/null
  fi

  # Copy the production binary to the Tauri binaries dir
  SIDECAR_NAME="dialekt-server-${TARGET}"
  if [ "$PLATFORM" = "windows" ]; then
    SIDECAR_NAME="${SIDECAR_NAME}.exe"
    cp "$PYTHON_DIR/dist/dialekt-server.exe" "$BINARIES_DIR/$SIDECAR_NAME"
  else
    cp "$PYTHON_DIR/dist/dialekt-server" "$BINARIES_DIR/$SIDECAR_NAME"
    chmod +x "$BINARIES_DIR/$SIDECAR_NAME"
  fi
  echo "  Sidecar → $BINARIES_DIR/$SIDECAR_NAME"

  # Sign the sidecar with hardened runtime on macOS (required for notarization)
  if [ "$PLATFORM" = "macos" ] && [ -n "${APPLE_SIGNING_IDENTITY:-}" ]; then
    echo "→ Signing sidecar with hardened runtime..."
    codesign --force --options runtime \
      --entitlements "$TAURI_DIR/src-tauri/Entitlements.plist" \
      --sign "$APPLE_SIGNING_IDENTITY" \
      --timestamp \
      "$BINARIES_DIR/$SIDECAR_NAME"
    echo "  Sidecar signed: $APPLE_SIGNING_IDENTITY"
  fi
fi

# ── Step 3: Build Tauri desktop app ──────────────────────────────────────────

echo "→ Building Tauri app..."
source "$HOME/.nvm/nvm.sh" 2>/dev/null || true
cd "$TAURI_DIR"
npm install --silent

case "$PLATFORM" in
  macos)
    npm run tauri build -- --target universal-apple-darwin
    echo ""
    echo "  Output: src-tauri/target/universal-apple-darwin/release/bundle/dmg/"

    # Notarize the .dmg if Apple credentials are available
    if [ -n "${APPLE_ID:-}" ] && [ -n "${APPLE_PASSWORD:-}" ] && [ -n "${APPLE_TEAM_ID:-}" ]; then
      echo "→ Notarizing .dmg with Apple..."
      DMG_PATH="$(ls "$TAURI_DIR/src-tauri/target/universal-apple-darwin/release/bundle/dmg/"*.dmg 2>/dev/null | head -1)"
      if [ -n "$DMG_PATH" ]; then
        xcrun notarytool submit "$DMG_PATH" \
          --apple-id "$APPLE_ID" \
          --password "$APPLE_PASSWORD" \
          --team-id "$APPLE_TEAM_ID" \
          --wait
        xcrun stapler staple "$DMG_PATH"
        echo "  ✓ Notarization complete — stapled to $DMG_PATH"
      else
        echo "  ⚠ No .dmg found to notarize"
      fi
    else
      echo "  (Skipping notarization — APPLE_ID / APPLE_PASSWORD / APPLE_TEAM_ID not set)"
    fi
    ;;
  linux)
    npm run tauri build
    echo ""
    echo "  Output:"
    echo "    .deb  → src-tauri/target/release/bundle/deb/"
    echo "    .AppImage → src-tauri/target/release/bundle/appimage/"
    ;;
  windows)
    npm run tauri build
    echo ""
    echo "  Output: src-tauri/target/release/bundle/nsis/"
    ;;
  python-only)
    echo "  (Skipped Tauri build — python-only mode)"
    ;;
esac

echo ""
echo "  ✓ Build complete"
echo ""
