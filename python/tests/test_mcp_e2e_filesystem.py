"""End-to-end integration tests: real filesystem MCP server through the
full dialekt stack.

This is the finish-line verification for Этап 1. Every test spawns
``@modelcontextprotocol/server-filesystem`` via ``npx -y``, bounded
to a pytest tmp_path directory. The tool call travels the full
stack end-to-end:

    manifest load
      → MCPClientManager (Commit 7)
      → MCPRuntime (Commit 9) with consent gate
      → SyncMCPNamespace (Commit 10)
      → npx subprocess + JSON-RPC handshake
      → filesystem tool call
      → subprocess response
      → audit rows in real SQLite audit_log

Tests auto-skip when ``npx`` or the server package isn't available
(CI without Node will still go green; local dev runs the full stack).
"""
import asyncio
import json
import shutil
import sqlite3
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from dialekt.mcp import (
    AutoApproveProvider,
    AutoDenyProvider,
    MCPConsentDenied,
    NoAuth,
    PromptConsentProvider,
    ConsentDecision,
)
from dialekt.mcp.manager import MCPClientManager
from dialekt.mcp.runtime import MCPRuntime
from dialekt.mcp.sync_bridge import create_sync_mcp
from dialekt.mcp.transport import StdioTransportSpec


NPX = shutil.which("npx")
SKIP_REASON = "npx not on PATH — filesystem MCP tests require Node."


def _fs_transport(sandbox: Path) -> StdioTransportSpec:
    """Spawn @modelcontextprotocol/server-filesystem bounded to ``sandbox``."""
    return StdioTransportSpec(
        command=[
            NPX,
            "-y",
            "@modelcontextprotocol/server-filesystem",
            str(sandbox),
        ],
        timeout_seconds=60.0,  # npx + server start is noticeable on first run
    )


def _audit_rows(db_path: Path, kind: str | None = None) -> list[dict]:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        if kind is None:
            cur = conn.execute(
                "SELECT * FROM audit_log ORDER BY id"
            )
        else:
            cur = conn.execute(
                "SELECT * FROM audit_log WHERE kind=? ORDER BY id", (kind,)
            )
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Connectivity smoke — prove the server spawns and advertises tools.
# ---------------------------------------------------------------------------


@pytest.mark.skipif(NPX is None, reason=SKIP_REASON)
def test_filesystem_server_advertises_expected_tools(tmp_path):
    """The filesystem server exports `read_file`, `write_file`,
    `list_directory`, and friends. If we can list them, the whole
    transport + handshake + SDK stack is up."""
    async def run():
        mgr = MCPClientManager(agent_id="fs-smoke")
        try:
            client = await mgr.get_client("fs", _fs_transport(tmp_path))
            result = await client.list_tools()
            names = {t.name for t in result.tools}
            # Cover the core tools we'll rely on in later tests. The
            # server's surface is wider; we only care that at least
            # these are present.
            assert "read_text_file" in names or "read_file" in names, (
                f"missing read tool. Advertised: {sorted(names)}"
            )
            assert "write_file" in names, (
                f"missing write_file. Advertised: {sorted(names)}"
            )
            assert "list_directory" in names, (
                f"missing list_directory. Advertised: {sorted(names)}"
            )
        finally:
            await mgr.shutdown()

    asyncio.run(run())


# ---------------------------------------------------------------------------
# Happy path: read via consent-gated runtime.
# ---------------------------------------------------------------------------


@pytest.mark.skipif(NPX is None, reason=SKIP_REASON)
def test_read_file_via_runtime_autonomous(tmp_path):
    """Autonomous agent reads a file the filesystem server exposes.
    No consent needed (read is non-destructive AND autonomy is auto).
    """
    target = tmp_path / "hello.txt"
    target.write_text("dialekt-e2e-marker\n")

    events: list[dict] = []

    def audit(**payload):
        events.append(payload)

    async def run():
        mgr = MCPClientManager(
            agent_id="fs-read", audit_callback=audit
        )
        runtime = MCPRuntime(
            manager=mgr,
            server_specs={"fs": (_fs_transport(tmp_path), NoAuth(), 60.0)},
            consent_provider=AutoApproveProvider(),
            audit_callback=audit,
            autonomy="autonomous",
            agent_id="fs-read",
        )
        try:
            # Server name varies across versions; try both.
            read_tool = await _pick_read_tool(runtime)
            result = await runtime.invoke_tool(
                "fs", read_tool, {"path": str(target)}
            )
            assert result.isError is False
            # FS content lands in the first text block.
            text = getattr(result.content[0], "text", None)
            assert text is not None and "dialekt-e2e-marker" in text
        finally:
            await runtime.shutdown()

    asyncio.run(run())

    # No consent audit rows under autonomous.
    kinds = [e["kind"] for e in events]
    assert "mcp_consent_requested" not in kinds
    assert "mcp_consent_decision" not in kinds
    assert any(
        e["kind"] == "mcp_tool_call" and e["result"] == "success"
        for e in events
    )


async def _pick_read_tool(runtime) -> str:
    """Return whichever of `read_text_file` / `read_file` the server
    actually advertises. Newer versions renamed the tool."""
    spec = runtime._server_specs["fs"]
    transport, credentials, _ = spec
    client = await runtime._manager.get_client(
        "fs", transport, credentials
    )
    result = await client.list_tools()
    names = {t.name for t in result.tools}
    for candidate in ("read_text_file", "read_file"):
        if candidate in names:
            return candidate
    raise RuntimeError(
        f"neither read_text_file nor read_file advertised: {names}"
    )


# ---------------------------------------------------------------------------
# Destructive write + consent approved via prompt.
# ---------------------------------------------------------------------------


@pytest.mark.skipif(NPX is None, reason=SKIP_REASON)
def test_write_file_destructive_consent_approved(tmp_path):
    """`write_file` hits the heuristic (name contains 'write'). With
    autonomy=ask-before-write, the runtime prompts; we approve via
    the test's prompt fn; the write goes through; the audit trail
    shows `mcp_consent_requested`, `mcp_consent_decision` (approved),
    and `mcp_tool_call` with `extra.consent_id` linking back.
    """
    out_path = tmp_path / "written.txt"
    events: list[dict] = []
    prompted: list = []

    def audit(**payload):
        # Return a fake row id so consent_id linking has something
        # to work with — production code gets a real id from the
        # POST /audit/log endpoint.
        events.append(payload)
        return {"id": len(events)}

    async def prompt(req):
        prompted.append(req)
        return ConsentDecision.APPROVED

    async def run():
        mgr = MCPClientManager(agent_id="fs-write", audit_callback=audit)
        runtime = MCPRuntime(
            manager=mgr,
            server_specs={"fs": (_fs_transport(tmp_path), NoAuth(), 60.0)},
            consent_provider=PromptConsentProvider(prompt),
            audit_callback=audit,
            autonomy="ask-before-write",
            agent_id="fs-write",
            binding_id="fs-write-1",
        )
        try:
            result = await runtime.invoke_tool(
                "fs",
                "write_file",
                {"path": str(out_path), "content": "hello from dialekt e2e"},
            )
            assert result.isError is False
        finally:
            await runtime.shutdown()

    asyncio.run(run())

    # File actually landed.
    assert out_path.exists()
    assert "hello from dialekt e2e" in out_path.read_text()

    # Exactly one prompt was fired (the destructive one).
    assert len(prompted) == 1
    assert prompted[0].tool_name == "write_file"
    assert prompted[0].destructive is True

    # Audit trail: consent req + consent decision (approved) + tool call.
    req_rows = [e for e in events if e["kind"] == "mcp_consent_requested"]
    dec_rows = [e for e in events if e["kind"] == "mcp_consent_decision"]
    call_rows = [e for e in events if e["kind"] == "mcp_tool_call"]

    assert len(req_rows) == 1
    assert len(dec_rows) == 1
    assert len(call_rows) == 1

    assert dec_rows[0]["result"] == "approved"
    assert dec_rows[0]["error_kind"] is None

    # consent_id linking: tool_call.extra.consent_id == decision row id.
    tool_call = call_rows[0]
    assert tool_call["extra"] is not None
    consent_id = tool_call["extra"].get("consent_id")
    assert consent_id is not None
    # The decision row's synthetic id from the audit cb.
    assert consent_id == events.index(dec_rows[0]) + 1


# ---------------------------------------------------------------------------
# Consent denial path.
# ---------------------------------------------------------------------------


@pytest.mark.skipif(NPX is None, reason=SKIP_REASON)
def test_write_file_denial_raises_and_leaves_fs_untouched(tmp_path):
    """Deny the write — file must not exist, agent sees MCPConsentDenied."""
    out_path = tmp_path / "denied.txt"
    events: list[dict] = []

    def audit(**p):
        events.append(p)
        return {"id": len(events)}

    async def run():
        mgr = MCPClientManager(agent_id="fs-deny", audit_callback=audit)
        runtime = MCPRuntime(
            manager=mgr,
            server_specs={"fs": (_fs_transport(tmp_path), NoAuth(), 60.0)},
            consent_provider=AutoDenyProvider(),
            audit_callback=audit,
            autonomy="ask-before-write",
            agent_id="fs-deny",
        )
        try:
            with pytest.raises(MCPConsentDenied):
                await runtime.invoke_tool(
                    "fs",
                    "write_file",
                    {"path": str(out_path), "content": "should not land"},
                )
        finally:
            await runtime.shutdown()

    asyncio.run(run())

    # File was never written.
    assert not out_path.exists()

    # Decision row records the denial; no tool_call row.
    dec_rows = [e for e in events if e["kind"] == "mcp_consent_decision"]
    call_rows = [e for e in events if e["kind"] == "mcp_tool_call"]
    assert len(dec_rows) == 1
    assert dec_rows[0]["result"] == "denied"
    # Denial isn't an error — error_kind stays NULL.
    assert dec_rows[0]["error_kind"] is None
    assert len(call_rows) == 0


# ---------------------------------------------------------------------------
# Sync namespace drives the whole stack.
# ---------------------------------------------------------------------------


@pytest.mark.skipif(NPX is None, reason=SKIP_REASON)
def test_sync_namespace_reads_file_end_to_end(tmp_path):
    """Exercise the full ``ctx.mcp.fs.read_*(...)`` agent-author
    syntax — async namespace wrapped in sync bridge, called from a
    worker thread."""
    target = tmp_path / "hello.txt"
    target.write_text("sync-bridge-verified\n")

    async def run():
        mgr = MCPClientManager(agent_id="fs-sync")
        runtime = MCPRuntime(
            manager=mgr,
            server_specs={"fs": (_fs_transport(tmp_path), NoAuth(), 60.0)},
            consent_provider=AutoApproveProvider(),
            autonomy="autonomous",
            agent_id="fs-sync",
        )
        adapter = create_sync_mcp(runtime)

        read_tool = await _pick_read_tool(runtime)

        def call_from_thread():
            server = adapter.namespace.fs
            tool_callable = getattr(server, read_tool)
            return tool_callable(path=str(target))

        try:
            result = await asyncio.to_thread(call_from_thread)
            text = getattr(result.content[0], "text", None)
            assert text is not None and "sync-bridge-verified" in text
        finally:
            await adapter.shutdown()

    asyncio.run(run())


# ---------------------------------------------------------------------------
# Full audit round-trip through POST /audit/log.
# ---------------------------------------------------------------------------


@pytest.mark.skipif(NPX is None, reason=SKIP_REASON)
def test_tool_call_writes_audit_row_via_http_endpoint(tmp_path, monkeypatch):
    """Wire MCPClientManager's audit callback through PluginContext
    so writes go to the real /audit/log server endpoint. Verify the
    SQLite audit_log table has the expected row afterwards.
    """
    # Fresh dialekt app with its DB pointed at tmp_path.
    monkeypatch.setenv("HOME", str(tmp_path))
    import importlib
    import server as server_module

    importlib.reload(server_module)
    assert str(server_module.DB_PATH).startswith(str(tmp_path))

    target = tmp_path / "audit_me.txt"
    target.write_text("audit-target\n")

    with TestClient(server_module.app) as _client:
        from dialekt.llm._plugin_context import PluginContext

        ctx = PluginContext(app=server_module.app)
        mgr = ctx.new_mcp_manager(agent_id="fs-audit")
        runtime = MCPRuntime(
            manager=mgr,
            server_specs={"fs": (_fs_transport(tmp_path), NoAuth(), 60.0)},
            consent_provider=AutoApproveProvider(),
            audit_callback=ctx._default_audit_callback,
            autonomy="autonomous",
            agent_id="fs-audit",
            binding_id="fs-audit-binding",
        )

        async def run():
            try:
                read_tool = await _pick_read_tool(runtime)
                await runtime.invoke_tool(
                    "fs", read_tool, {"path": str(target)}
                )
            finally:
                await runtime.shutdown()

        asyncio.run(run())
        ctx.close()

    rows = _audit_rows(server_module.DB_PATH, kind="mcp_tool_call")
    assert len(rows) == 1
    row = rows[0]
    assert row["result"] == "success"
    assert row["target"] == "fs"
    assert row["agent_id"] == "fs-audit"
    assert row["binding_id"] == "fs-audit-binding"
    assert row["duration_ms"] is not None


# ---------------------------------------------------------------------------
# Rate limit trip.
# ---------------------------------------------------------------------------


@pytest.mark.skipif(NPX is None, reason=SKIP_REASON)
def test_rate_limit_blocks_excess_calls(tmp_path):
    """Tight limit of 3 → 4th call raises MCPRateLimitError before
    hitting the subprocess. The connection stays open; limit is
    advisory at dialekt's layer, not server's."""
    from dialekt.mcp import MCPRateLimitError

    target = tmp_path / "rate.txt"
    target.write_text("rate-target\n")

    events: list[dict] = []

    async def run():
        mgr = MCPClientManager(
            agent_id="fs-rate",
            audit_callback=lambda **p: events.append(p),
            rate_limit_per_minute=3,
        )
        runtime = MCPRuntime(
            manager=mgr,
            server_specs={"fs": (_fs_transport(tmp_path), NoAuth(), 60.0)},
            consent_provider=AutoApproveProvider(),
            audit_callback=lambda **p: events.append(p),
            autonomy="autonomous",
            agent_id="fs-rate",
        )
        try:
            read_tool = await _pick_read_tool(runtime)
            # 3 successful calls.
            for _ in range(3):
                await runtime.invoke_tool(
                    "fs", read_tool, {"path": str(target)}
                )
            # 4th trips the limit.
            with pytest.raises(MCPRateLimitError):
                await runtime.invoke_tool(
                    "fs", read_tool, {"path": str(target)}
                )
        finally:
            await runtime.shutdown()

    asyncio.run(run())

    # Three successful tool_call rows; one rate_limited tool_call row.
    results = [
        e["result"] for e in events if e["kind"] == "mcp_tool_call"
    ]
    assert results.count("success") == 3
    assert "rate_limited" in results
