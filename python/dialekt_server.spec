# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for dialekt's Python backend
#
# Build: pyinstaller dialekt_server.spec
# Output: dist/dialekt-server (or dist/dialekt-server.exe on Windows)
#
# This binary is packaged as a Tauri sidecar in the desktop app.
# See: https://tauri.app/v1/guides/building/sidecar

import platform

BINARY_NAME = "dialekt-server"
# Tauri sidecar naming convention: <name>-<target-triple>
# The build system renames this automatically when bundling.

block_cipher = None

a = Analysis(
    ["server.py"],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[
        # FastAPI + async
        "anyio",
        "anyio._backends._asyncio",
        "anyio._backends._trio",
        "uvicorn",
        "uvicorn.loops.asyncio",
        "uvicorn.protocols.http.h11_impl",
        "uvicorn.lifespan.on",
        # aiosqlite
        "aiosqlite",
        # open-interpreter
        "interpreter",
        "interpreter.core",
        # psutil
        "psutil",
        # httpx
        "httpx",
        # starlette
        "starlette.middleware",
        "starlette.routing",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Exclude asyncpg — replaced by aiosqlite
        "asyncpg",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name=BINARY_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,  # UPX can break some binaries; disable for safety
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,  # Keep console for server logs (hidden by Tauri on release)
    disable_windowed_traceback=False,
    target_arch=None,  # None = native arch; use "universal2" for macOS universal
    codesign_identity=None,
    entitlements_file=None,
)
