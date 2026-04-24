"""CLI entry point for the dialekt MCP server.

Invoked by Claude Desktop (and other MCP hosts) via::

    dialekt-mcp --api-key KEY [--backend URL] [--config PATH]

The binary lives on PATH after the Tauri installer symlinks it;
developers run ``python -m dialekt.mcp.server.cli`` directly.

Exit codes:
    0 — clean exit (stdio pipe closed normally)
    1 — generic/unknown error
    2 — authentication failure (AuthError)
    3 — backend unreachable (Decision 3 precondition)
    4 — config error (malformed toml, missing required field, etc.)
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from typing import Optional

import httpx

from dialekt.mcp.server.auth import AuthError, validate_api_key
from dialekt.mcp.server.config import load_config, ServerConfig
from dialekt.mcp.server.server import MCPServer


log = logging.getLogger("dialekt.mcp.server.cli")


EXIT_OK = 0
EXIT_GENERIC = 1
EXIT_AUTH = 2
EXIT_BACKEND_UNREACHABLE = 3
EXIT_CONFIG = 4


def _parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="dialekt-mcp",
        description=(
            "Serve the dialekt MCP server over stdio. Invoked by "
            "external MCP hosts (Claude Desktop, Cursor, custom). "
            "Requires the dialekt desktop app to be running on "
            "127.0.0.1:8765 by default."
        ),
    )
    parser.add_argument(
        "--api-key",
        default=None,
        help=(
            "API key from dialekt → Settings → Integrations. Required "
            "unless DIALEKT_MCP_API_KEY env var is set or --dev."
        ),
    )
    parser.add_argument(
        "--backend",
        default=None,
        help=(
            "dialekt backend URL (default: http://127.0.0.1:8765 or "
            "DIALEKT_BACKEND_URL env)."
        ),
    )
    parser.add_argument(
        "--config",
        default=None,
        help=(
            "Path to mcp-server.toml (default: ~/.dialekt/mcp-server.toml "
            "or DIALEKT_MCP_CONFIG_PATH env)."
        ),
    )
    parser.add_argument(
        "--dev",
        action="store_true",
        help=(
            "Development mode: skip API-key authentication. Only use "
            "against a local dialekt you control."
        ),
    )
    return parser.parse_args(argv)


def _configure_logging(level: str) -> None:
    # Log to STDERR — stdout is the MCP JSON-RPC channel and any
    # stray bytes there would corrupt the protocol.
    logging.basicConfig(
        level=level,
        stream=sys.stderr,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )


def _ping_backend(backend_url: str, timeout: float = 3.0) -> bool:
    """Decision 3 precondition: the dialekt desktop app must be
    running. A quick GET /health confirms the backend is up before
    we accept a client connection — if it's down, fail loudly with
    a hint rather than advertise tools that will all 500."""
    try:
        with httpx.Client(base_url=backend_url, timeout=timeout) as client:
            response = client.get("/health")
            return response.status_code < 500
    except Exception:
        return False


def main(argv: Optional[list[str]] = None) -> int:
    args = _parse_args(argv)

    try:
        config = load_config(args.config)
    except Exception as e:
        print(
            f"dialekt-mcp: failed to load config: {e}",
            file=sys.stderr,
        )
        return EXIT_CONFIG

    # CLI flag wins over env var wins over config default.
    if args.backend:
        config = config.model_copy(update={"backend_url": args.backend})

    _configure_logging(config.log_level)

    # Backend precondition (Decision 3).
    if not _ping_backend(config.backend_url):
        print(
            f"dialekt-mcp: cannot reach dialekt backend at {config.backend_url}.\n"
            "\n"
            "This MCP server requires the dialekt desktop application "
            "to be running.\n"
            "\n"
            "To fix:\n"
            "  1. Open the dialekt desktop app\n"
            "  2. Verify it's running: curl " + config.backend_url + "/health\n"
            "  3. Restart Claude Desktop (or re-launch this connection)\n"
            "\n"
            "If dialekt runs on a different port, set the DIALEKT_BACKEND_URL\n"
            "environment variable in your MCP host's config, or pass --backend.\n",
            file=sys.stderr,
        )
        return EXIT_BACKEND_UNREACHABLE

    # Authenticate — --api-key > DIALEKT_MCP_API_KEY > dev-mode bypass.
    api_key = args.api_key or os.environ.get("DIALEKT_MCP_API_KEY")
    active_key = None
    if not args.dev:
        try:
            active_key = validate_api_key(config, api_key)
        except AuthError as e:
            print(f"dialekt-mcp: {e}", file=sys.stderr)
            return EXIT_AUTH

    # Build the PluginContext used by tool handlers to proxy HTTP
    # calls into the dialekt backend. http-mode (base_url) is the
    # right transport here — we're a separate process, not sharing
    # the backend's ASGI app.
    from dialekt.llm._plugin_context import PluginContext

    ctx = PluginContext(base_url=config.backend_url)

    # Default audit callback POSTs to /audit/log (same endpoint that
    # Этап 1 shipped). Reuse the PluginContext's default_audit_callback
    # to keep one audit path across client + server.
    audit_cb = ctx._default_audit_callback

    server = MCPServer(
        config=config,
        plugin_context=ctx,
        audit_callback=audit_cb,
    )
    if active_key is not None:
        server.bind_active_key(active_key)
    server.register_tools()

    try:
        server.run_stdio()
    except KeyboardInterrupt:
        log.info("dialekt-mcp interrupted, exiting cleanly")
        return EXIT_OK
    except Exception as e:
        log.exception("dialekt-mcp crashed: %s", e)
        return EXIT_GENERIC
    finally:
        ctx.close()

    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
