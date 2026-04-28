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
import importlib.util
from pathlib import Path

from PyInstaller.utils.hooks import copy_metadata, collect_data_files

BINARY_NAME = "dialekt-server"
HERE = Path(os.path.abspath(SPECPATH))

# Packages that introspect their own version via importlib.metadata at
# import time. PyInstaller doesn't bundle *.dist-info by default, so the
# frozen binary raises PackageNotFoundError on the first import — for
# `readchar` (transitive: interpreter → inquirer → readchar) this only
# fires when a chat WS opens, which manifested as endless WS-reconnect
# and a "backend offline" badge on macOS bundle builds.
METADATA_PACKAGES = ["readchar"]
metadata_datas = []
for pkg in METADATA_PACKAGES:
    try:
        metadata_datas += copy_metadata(pkg)
    except Exception:
        # Best-effort: if a future refactor drops the dep, don't block
        # the build. The runtime import will still raise the same
        # PackageNotFoundError, surfacing the regression in tests.
        pass

# Packages that ship data files alongside Python sources (JSON, YAML,
# templates) and reach for them at import time via pkgutil.get_data
# or pkg_resources. PyInstaller's analyser misses these unless told.
# - `yaspin` reads data/spinners.json on `import yaspin.spinners`
#   (transitive: interpreter → terminal_interface → scan_code → yaspin).
#   Same failure mode as the readchar one above — WS chat dies on first
#   make_interpreter() call. Both bugs flushed out by smoke-testing the
#   chat path post-bundle, not just import-server.
DATA_FILE_PACKAGES = [
    "yaspin",   # data/spinners.json — read by yaspin.spinners on import
    "litellm",  # litellm/model_prices_and_context_window_backup.json —
                # read by litellm/__init__.py on import via the model
                # cost map loader; failure surfaces the same way as
                # yaspin (WS dies on first chat connect).
]
data_file_datas = []
for pkg in DATA_FILE_PACKAGES:
    try:
        data_file_datas += collect_data_files(pkg)
    except Exception:
        pass

# sqlite_vec is skipped on windows-arm64 (no wheel + sdist requires py<3.12).
# Probe whether it's actually installed before listing it as a hidden import,
# otherwise PyInstaller emits a hard error on missing modules in some configs.
HAS_SQLITE_VEC = importlib.util.find_spec("sqlite_vec") is not None

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
        *metadata_datas,
        *data_file_datas,
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

        # tiktoken's encodings (cl100k_base etc.) are registered via the
        # tiktoken_ext namespace through Python entry-points. PyInstaller
        # doesn't traverse entry-point plugins, so the frozen binary
        # raises "Unknown encoding cl100k_base" the first time litellm
        # tokenises a prompt. Listing the public-encodings module forces
        # PyInstaller to include it; tiktoken_ext is the parent namespace.
        "tiktoken_ext",
        "tiktoken_ext.openai_public",

        # Misc
        "httpx",
        "psutil",
        "yaml",
        *(["sqlite_vec"] if HAS_SQLITE_VEC else []),
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Shrink binary: exclude things that aren't used on Linux.
        # Note: `matplotlib` was previously here but open-interpreter's
        # display.py calls lazy_import("matplotlib") at module load and
        # raises ModuleNotFoundError when find_spec returns None, even
        # though matplotlib itself is never used in our chat path.
        # Removing the exclude lets PyInstaller bundle the package and
        # silences the import-time check; the cost is ~30 MB on top of
        # the 126 MB sidecar.
        "tkinter",
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
