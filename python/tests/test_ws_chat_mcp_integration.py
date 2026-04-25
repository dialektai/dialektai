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
def test_ctx_mcp_resolves_inside_raw_thread_via_copy_context():
    """Regression for mentor P0: `bind_mcp_runtime` uses a ContextVar.
    OI runs in a raw `threading.Thread` — ContextVars don't inherit.
    The fix wraps the thread spawn in `contextvars.copy_context().run`.
    This test asserts the live resolution path (not just registry
    state): bind in an asyncio task, spawn a raw thread via
    `copy_context().run(...)`, call `ctx.mcp.<server>.<tool>(...)`
    from inside the thread, get back a real `CallToolResult`.
    """
    import contextvars
    import threading
    from dialekt.llm._plugin_context import bind_mcp_runtime, unbind_mcp_runtime, get_context

    async def run():
        srv._active_mcp_runtimes.clear()
        with tempfile.TemporaryDirectory() as sandbox:
            sandbox_path = Path(sandbox)
            (sandbox_path / "hello.txt").write_text("world")
            ws = FakeWS()
            manifest = {
                "autonomy": {"recommended": "ask-before-write"},
                "mcp_servers": [{
                    "name": "fs",
                    "transport": "stdio",
                    "command": [
                        NPX, "-y",
                        "@modelcontextprotocol/server-filesystem",
                        str(sandbox_path),
                    ],
                    "timeout_seconds": 60,
                }],
            }
            built = await srv._build_session_mcp_runtime(
                manifest=manifest, ws=ws, ws_id="t-thread",
                loop=asyncio.get_event_loop(), agent_id="agent-thread",
            )
            assert built is not None
            _runtime, _adapter, _manager, bind_token = built

            # Snapshot the context AFTER the bind so the worker thread
            # inherits the ContextVar.
            ctx_copy = contextvars.copy_context()
            captured: dict = {}

            def worker():
                try:
                    namespace = get_context().mcp
                    captured["namespace_class"] = type(namespace).__name__
                    server_proxy = namespace.fs
                    captured["server_proxy_class"] = type(server_proxy).__name__
                    # The strongest regression check: actually CALL a
                    # tool through the sync bridge from this raw worker
                    # thread. Without copy_context() this entire chain
                    # would have raised RuntimeError before the call.
                    # list_directory is a read-only fs MCP tool; the
                    # consent provider auto-approves non-destructive
                    # tools regardless of autonomy level.
                    result = server_proxy.list_directory(path=str(sandbox_path))
                    captured["call_returned"] = True
                    captured["result_type"] = type(result).__name__
                except Exception as e:
                    captured["error"] = repr(e)

            t = threading.Thread(target=lambda: ctx_copy.run(worker))
            t.start()
            # Use to_thread to avoid blocking the event loop — the sync
            # bridge dispatches the tool call BACK to this same loop
            # via asyncio.run_coroutine_threadsafe, and a plain
            # `t.join()` would deadlock against that dispatch.
            await asyncio.to_thread(t.join, 30.0)

            try:
                assert "error" not in captured, (
                    f"ctx.mcp resolution from raw thread failed: {captured.get('error')}"
                )
                assert "namespace_class" in captured, captured
                assert "server_proxy_class" in captured, captured
                assert captured.get("call_returned") is True, (
                    f"cross-thread tool call did not complete: {captured}"
                )
            finally:
                unbind_mcp_runtime(bind_token)
                await srv._shutdown_session_mcp_runtime("t-thread")

    asyncio.run(run())


def test_build_threads_manifest_allow_tools_into_runtime_policies():
    """v0.22: when manifest declares mcp_servers[].allow_tools or
    deny_tools, _build_session_mcp_runtime must construct a
    ToolPolicy and thread it into MCPRuntime so policy-blocked calls
    fast-fail at the gate. No real MCP subprocess needed — we
    inspect the runtime's _tool_policies dict directly."""
    from dialekt.mcp.runtime import ToolPolicy

    async def run():
        srv._active_mcp_runtimes.clear()
        ws = FakeWS()
        manifest = {
            "autonomy": {"recommended": "autonomous"},
            "mcp_servers": [
                {
                    "name": "github",
                    "transport": "stdio",
                    "command": ["echo"],
                    "allow_tools": ["search_repositories"],
                    "deny_tools": ["delete_repository"],
                    "timeout_seconds": 30,
                },
                {
                    "name": "no-scope",
                    "transport": "stdio",
                    "command": ["echo"],
                    "timeout_seconds": 30,
                },
            ],
        }
        built = await srv._build_session_mcp_runtime(
            manifest=manifest, ws=ws, ws_id="t-policy",
            loop=asyncio.get_event_loop(), agent_id="agent-policy",
        )
        assert built is not None
        runtime, _adapter, manager, _bind_token = built
        try:
            policies = runtime._tool_policies
            # Server WITH scoping → policy entry
            assert "github" in policies
            assert isinstance(policies["github"], ToolPolicy)
            assert policies["github"].allow == frozenset({"search_repositories"})
            assert policies["github"].deny == frozenset({"delete_repository"})
            # Server WITHOUT scoping → no entry (= "all tools allowed",
            # mentor backwards-compat)
            assert "no-scope" not in policies
        finally:
            srv._active_mcp_runtimes["t-policy"] = built
            await srv._shutdown_session_mcp_runtime("t-policy")

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

            # Force a real subprocess connect so shutdown has work to do.
            # Mentor P1: prior version asserted only registry semantics
            # while manager._clients stayed empty, making shutdown a
            # no-op. invoke_tool(...) opens the stdio MCP client; we
            # then assert it lands in the manager AND that shutdown
            # actually closes it (manager goes _shutdown=True).
            await runtime.invoke_tool("fs", "list_directory", arguments={"path": str(Path('.').resolve())[:0] or "/"})
            # Some servers may reject the path; we don't care about the
            # result — only that get_client got called and the manager
            # opened the subprocess.
            # The client cache lives at manager._clients; after
            # invoke_tool the "fs" entry must be present.
            assert "fs" in manager._clients, (
                "invoke_tool must have triggered manager.get_client('fs', ...)"
            )

            # Shutdown should close the client and flip the shutdown flag.
            await srv._shutdown_session_mcp_runtime("t-fs")
            assert "t-fs" not in srv._active_mcp_runtimes
            assert manager._shutdown is True, "manager.shutdown() must mark _shutdown"
    asyncio.run(run())
