"""End-to-end audit integration test for MCPClientManager.

Proves that a tool call through the manager → audit callback → the
``POST /audit/log`` endpoint → ``log_event`` → a row in the
``audit_log`` SQLite table. Both the success and the error path.

This is the test user explicitly flagged as must-have for Commit 7
(reminder task #15).
"""
import asyncio
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from dialekt.mcp import MCPServerUnavailableError
from dialekt.mcp.transport import StdioTransportSpec


FIXTURE = Path(__file__).parent / "fixtures" / "fastmcp_stdio_echo.py"


@pytest.fixture
def server_testclient(tmp_path, monkeypatch):
    """Fresh dialekt FastAPI app with DB pointed at a temp SQLite.

    Importing server.py runs at module level; we set DB_PATH before
    the _init_db task runs during startup. Each test gets a pristine
    audit_log table.
    """
    monkeypatch.setenv("HOME", str(tmp_path))
    # server imports ``DIALEKT_DIR = _HOME / ".dialekt"`` at module
    # load — if already imported, just repoint the constants.
    import importlib
    import server

    importlib.reload(server)

    # The reload re-reads HOME via Path.home(); confirm it landed.
    assert str(server.DB_PATH).startswith(str(tmp_path))

    with TestClient(server.app) as client:
        yield server, client


def _audit_rows_for_kind(server_module, kind: str) -> list[dict]:
    """Read all audit rows of a given kind directly from SQLite."""
    import sqlite3

    conn = sqlite3.connect(str(server_module.DB_PATH))
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.execute(
            "SELECT * FROM audit_log WHERE kind=? ORDER BY id", (kind,)
        )
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def test_success_call_tool_writes_audit_row(server_testclient):
    """call_tool → /audit/log endpoint → audit_log row with result=success."""
    server, client = server_testclient

    # Build a PluginContext backed by this app; fetch a manager.
    from dialekt.llm._plugin_context import PluginContext

    ctx = PluginContext(app=server.app)
    mgr = ctx.new_mcp_manager(agent_id="agent-e2e")

    transport = StdioTransportSpec(command=[sys.executable, "-u", str(FIXTURE)])

    async def run():
        try:
            result = await mgr.call_tool(
                "echo",
                "add",
                {"a": 2, "b": 5},
                transport=transport,
                binding_id="binding-e2e-1",
            )
            assert getattr(result.content[0], "text", None) == "7"
        finally:
            await mgr.shutdown()

    asyncio.run(run())
    ctx.close()

    rows = _audit_rows_for_kind(server, "mcp_tool_call")
    success = [r for r in rows if r["result"] == "success"]
    assert len(success) == 1
    row = success[0]
    assert row["action"] == "add"
    assert row["agent_id"] == "agent-e2e"
    assert row["binding_id"] == "binding-e2e-1"
    assert row["target"] == "echo"
    assert row["duration_ms"] is not None
    assert row["error_kind"] is None


def test_error_call_tool_writes_audit_row_with_error_kind(server_testclient):
    """Failed call → audit row with result != success and error_kind set."""
    server, client = server_testclient

    from dialekt.llm._plugin_context import PluginContext

    ctx = PluginContext(app=server.app)
    mgr = ctx.new_mcp_manager(agent_id="agent-e2e-err")

    bad_transport = StdioTransportSpec(
        command=["dialekt-nonexistent-binary-for-e2e"]
    )

    async def run():
        try:
            with pytest.raises(MCPServerUnavailableError):
                await mgr.call_tool(
                    "never-opens",
                    "list_repos",
                    {},
                    transport=bad_transport,
                    binding_id="binding-e2e-err",
                )
        finally:
            await mgr.shutdown()

    asyncio.run(run())
    ctx.close()

    rows = _audit_rows_for_kind(server, "mcp_tool_call")
    err = [r for r in rows if r["result"] == "server_unavailable"]
    assert len(err) == 1
    row = err[0]
    assert row["action"] == "list_repos"
    assert row["agent_id"] == "agent-e2e-err"
    assert row["binding_id"] == "binding-e2e-err"
    assert row["target"] == "never-opens"
    assert row["error_kind"] == "MCPServerUnavailableError"
