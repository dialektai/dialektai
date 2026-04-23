# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for dialekt's Python backend.
#
# Build:
#   source venv/bin/activate
#   pyinstaller --clean dialekt_server.spec
# Output:
#   dist/dialekt-server         (single-file binary, ~100-150 MB)
#
# The Tauri bundler picks this up via externalBin and renames it to
# dialekt-server-<target-triple> when building the .deb / AppImage.

import os
import sys
from pathlib import Path

BINARY_NAME = "dialekt-server"
HERE = Path(os.path.abspath(SPECPATH))

block_cipher = None

# Keep server.py as entry; pull in dialekt.llm and mcp_servers as packages
# so their routers and helpers are importable from the frozen app.
a = Analysis(
    ["server.py"],
    pathex=[str(HERE)],
    binaries=[],
    datas=[
        # Bundle the manifest validator's JSON schema so import-yaml works
        # without reading external files at runtime.
        # (dialekt_manifest_validator ships its schema inside the wheel, so
        #  PyInstaller collects it automatically via collect_data_files.)
    ],
    hiddenimports=[
        # FastAPI + starlette + uvicorn stack
        "anyio",
        "anyio._backends._asyncio",
        "uvicorn",
        "uvicorn.loops.asyncio",
        "uvicorn.loops.auto",
        "uvicorn.protocols.http.auto",
        "uvicorn.protocols.http.h11_impl",
        "uvicorn.protocols.http.httptools_impl",
        "uvicorn.protocols.websockets.auto",
        "uvicorn.protocols.websockets.websockets_impl",
        "uvicorn.protocols.websockets.wsproto_impl",
        "uvicorn.lifespan.on",
        "uvicorn.logging",
        "starlette",
        "starlette.middleware",
        "starlette.routing",
        "starlette.responses",
        "fastapi",
        "fastapi.responses",

        # SQLite (local) + PG/MySQL/ClickHouse MCP
        "aiosqlite",
        "asyncpg",
        "aiomysql",
        "pymysql",
        "clickhouse_connect",
        "clickhouse_connect.driver",
        "clickhouse_connect.driver.httputil",

        # Manifest validator (wheel is pip-installed, but PyInstaller
        # occasionally misses transitive submodules)
        "dialekt_manifest_validator",
        "dialekt_manifest_validator.schema",
        "dialekt_manifest_validator.validator",

        # Open Interpreter + litellm LLM stack
        "interpreter",
        "interpreter.core",
        "interpreter.core.core",
        "litellm",
        "litellm.llms",

        # dialekt's own modules (pkg discovery in frozen app)
        "dialekt",
        "dialekt.llm",
        "dialekt.llm.prompt_wrapper",
        "dialekt.llm.retry_loop",
        "dialekt.llm.few_shot_memory",
        "mcp_servers",
        "mcp_servers.postgres_mcp",
        "mcp_servers.mysql_mcp",
        "mcp_servers.clickhouse_mcp",
        "mcp_servers.schema_rag",

        # Secrets
        "keyring",
        "keyring.backends",
        "keyring.backends.SecretService",
        "keyring.backends.libsecret",
        "keyring.backends.kwallet",
        "keyring.backends.fail",
        "secretstorage",
        "jeepney",
        "jeepney.io.asyncio",

        # Misc
        "httpx",
        "psutil",
        "yaml",
        "sqlite_vec",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Shrink binary: exclude things that aren't used on Linux
        "tkinter",
        "matplotlib",
        "numpy.distutils",
        "scipy",
        "pandas",
        "PyQt5",
        "PyQt6",
        "PySide2",
        "PySide6",
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
    console=True,  # Logs visible in terminal (Tauri hides GUI-less by default)
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
