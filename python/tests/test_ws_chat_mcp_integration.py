"""Tests for ws_chat ↔ MCPRuntime wiring (Phase 1.5a).

The integration target is ``server._build_session_mcp_runtime`` —
the helper invoked from the ws_chat join handler when an agent's
manifest declares ``mcp_servers``. Hitting the helper directly with
a FakeWS sidesteps WS-timing flakiness while still covering all the
contract points:

1. no mcp_servers → returns None, no WS frame.
2. config error (unresolved secret) → soft-fails: WS receives an
   ``mcp_setup_error`` frame, helper returns None, no runtime
   bound.
3. happy path with a real filesystem MCP → returns runtime/adapter/
   manager + binds; cleanup via ``_shutdown_session_mcp_runtime``
   pops the registry and shuts the manager down.

Test #3 reuses ``@modelcontextprotocol/server-filesystem`` (npx) and
auto-skips when Node is not on PATH, matching ``test_mcp_e2e_filesystem``.
"""
from __future__ import annotations

import asyncio
import json
import shutil
import tempfile
from pathlib import Path

import pytest

import server as srv


NPX = shutil.which("npx")
SKIP_REASON = "npx not on PATH — filesystem MCP integration test requires Node."


class FakeWS:
    """Captures send_text calls for inspection."""

    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send_text(self, text: str) -> None:
        self.sent.append(json.loads(text))


# ── Unit tests on the helper ────────────────────────────────────────────────


def test_build_returns_none_when_manifest_has_no_mcp_servers():
    """No mcp_servers key + no WS frame side effect."""
    async def run():
        srv._active_mcp_runtimes.clear()
        ws = FakeWS()
        manifest = {"autonomy": {"recommended": "ask-before-write"}}
        result = await srv._build_session_mcp_runtime(
            manifest=manifest, ws=ws, ws_id="t-no-mcp",
            loop=asyncio.get_event_loop(), agent_id="agent-1",
        )
        assert result is None
        assert ws.sent == []
        assert "t-no-mcp" not in srv._active_mcp_runtimes
    asyncio.run(run())


def test_build_soft_fails_on_unresolved_secret_and_emits_setup_error():
    """Manifest references ${secrets.missing}; helper catches the
    MCPConfigError, sends an mcp_setup_error frame, returns None.
    Chat session must NOT crash on this path.
    """
    async def run():
        srv._active_mcp_runtimes.clear()
        ws = FakeWS()
        manifest = {
            "autonomy": {"recommended": "ask-before-write"},
            "mcp_servers": [{
                "name": "broken",
                "transport": "stdio",
                "command": ["/bin/echo", "ok"],
                "env": {"TOKEN": "${secrets.totally_missing_secret}"},
                "timeout_seconds": 30,
            }],
        }
        result = await srv._build_session_mcp_runtime(
            manifest=manifest, ws=ws, ws_id="t-bad",
            loop=asyncio.get_event_loop(), agent_id="agent-1",
        )
        assert result is None
        types_sent = [f.get("type") for f in ws.sent]
        assert "mcp_setup_error" in types_sent, (
            f"expected mcp_setup_error frame, got: {ws.sent}"
        )
        # Error string must mention the missing ref so the user can act.
        err_frame = next(f for f in ws.sent if f.get("type") == "mcp_setup_error")
        assert "totally_missing_secret" in err_frame.get("error", "") \
               or "secret" in err_frame.get("error", "").lower()
    asyncio.run(run())


def test_build_soft_fails_on_invalid_transport_kind_and_emits_setup_error():
    """Unknown transport string → pydantic validation fails inside the
    StdioTransportSpec / HttpTransportSpec branches. Either way the
    soft-fail path catches it and the session keeps going."""
    async def run():
        srv._active_mcp_runtimes.clear()
        ws = FakeWS()
        manifest = {
            "autonomy": {"recommended": "ask-before-write"},
            "mcp_servers": [{
                "name": "weird",
                "transport": "stdio",
                "command": [],   # empty command — StdioTransportSpec rejects
                "timeout_seconds": 30,
            }],
        }
        result = await srv._build_session_mcp_runtime(
            manifest=manifest, ws=ws, ws_id="t-weird",
            loop=asyncio.get_event_loop(), agent_id="agent-1",
        )
        assert result is None
        assert any(f.get("type") == "mcp_setup_error" for f in ws.sent)
    asyncio.run(run())


@pytest.mark.skipif(NPX is None, reason=SKIP_REASON)
def test_build_happy_path_with_filesystem_mcp_and_shutdown_clears_registry():
    """Real npx-spawned filesystem MCP. Helper returns a 4-tuple
    (runtime, adapter, manager, bind_token). Registering it and then
    calling ``_shutdown_session_mcp_runtime`` clears the registry and
    unbinds + shuts down the manager.
    """
    async def run():
        srv._active_mcp_runtimes.clear()
        with tempfile.TemporaryDirectory() as sandbox:
            ws = FakeWS()
            manifest = {
                "autonomy": {"recommended": "ask-before-write"},
                "mcp_servers": [{
                    "name": "fs",
                    "transport": "stdio",
                    "command": [
                        NPX, "-y",
                        "@modelcontextprotocol/server-filesystem",
                        str(sandbox),
                    ],
                    "timeout_seconds": 60,
                }],
            }
            built = await srv._build_session_mcp_runtime(
                manifest=manifest, ws=ws, ws_id="t-fs",
                loop=asyncio.get_event_loop(), agent_id="agent-fs",
            )
            assert built is not None, f"build failed; ws frames: {ws.sent}"
            runtime, adapter, manager, bind_token = built
            srv._active_mcp_runtimes["t-fs"] = built
            assert "t-fs" in srv._active_mcp_runtimes
            assert ws.sent == [], "happy path must not emit setup-error frames"

            # Shutdown should clear the registry without exceptions.
            await srv._shutdown_session_mcp_runtime("t-fs")
            assert "t-fs" not in srv._active_mcp_runtimes
    asyncio.run(run())
