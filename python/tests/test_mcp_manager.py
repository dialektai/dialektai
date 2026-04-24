"""Tests for MCPClientManager — the integration point where
lazy-init, caching, rate-limit, timeout, error classification, and
audit emission all collide.
"""
import asyncio
import sys
import time
from pathlib import Path

import pytest

from dialekt.mcp import (
    MCPClient,
    MCPRateLimitError,
    MCPServerUnavailableError,
    MCPTimeoutError,
    NoAuth,
    StdioTransportSpec,
)
from dialekt.mcp.manager import MCPClientManager


FIXTURE = Path(__file__).parent / "fixtures" / "fastmcp_stdio_echo.py"


def _spawn_cmd() -> list[str]:
    return [sys.executable, "-u", str(FIXTURE)]


# ---------------------------------------------------------------------------
# Unit tests: rate limiter + error classification plumbing.
# ---------------------------------------------------------------------------


def test_rate_limit_breach_raises_and_emits_audit():
    """Synthetic rate window — clock-mock, no real MCP connection."""
    events: list[dict] = []

    def sync_audit(**payload):
        events.append(payload)

    # Monotonic clock: advance by 1s per call so the sliding window
    # keeps all entries inside.
    time_now = [0.0]

    def fake_clock():
        return time_now[0]

    mgr = MCPClientManager(
        agent_id="a1",
        audit_callback=sync_audit,
        rate_limit_per_minute=3,
        clock=fake_clock,
    )

    async def run():
        # 3 calls fit, 4th trips.
        for _ in range(3):
            mgr._check_rate_limit()
            time_now[0] += 1.0
        with pytest.raises(MCPRateLimitError):
            mgr._check_rate_limit()

        # Give the fire-and-forget audit task a chance to execute.
        await asyncio.sleep(0.05)

    asyncio.run(run())

    # Exactly one audit row for the breach.
    rate_events = [e for e in events if e.get("result") == "rate_limited"]
    assert len(rate_events) == 1
    assert rate_events[0]["error_kind"] == "MCPRateLimitError"
    assert rate_events[0]["agent_id"] == "a1"


def test_rate_limit_window_slides():
    """Entries older than 60s are evicted; the limit resets."""
    time_now = [0.0]

    def fake_clock():
        return time_now[0]

    mgr = MCPClientManager(
        agent_id="a", rate_limit_per_minute=2, clock=fake_clock
    )
    mgr._check_rate_limit()
    time_now[0] += 1.0
    mgr._check_rate_limit()
    time_now[0] += 0.5
    with pytest.raises(MCPRateLimitError):
        mgr._check_rate_limit()
    # Advance 60s past the oldest entry; window slides out.
    time_now[0] += 61.0
    mgr._check_rate_limit()  # no error


# ---------------------------------------------------------------------------
# Integration tests: manager drives a real stdio MCP subprocess.
# ---------------------------------------------------------------------------


def test_manager_lazy_opens_then_caches_client():
    async def run():
        mgr = MCPClientManager(agent_id="agent-1")
        transport = StdioTransportSpec(command=_spawn_cmd())
        try:
            c1 = await mgr.get_client("echo", transport)
            c2 = await mgr.get_client("echo", transport)
            assert c1 is c2, "cached client expected"
            assert isinstance(c1, MCPClient)
        finally:
            await mgr.shutdown()

    asyncio.run(run())


def test_manager_call_tool_success_emits_audit():
    """Happy path — call_tool succeeds and emits a 'success' audit row
    with agent_id / binding_id / target / action / duration_ms."""
    events: list[dict] = []

    def audit(**p):
        events.append(p)

    async def run():
        mgr = MCPClientManager(
            agent_id="agent-ok",
            audit_callback=audit,
        )
        transport = StdioTransportSpec(command=_spawn_cmd())
        try:
            result = await mgr.call_tool(
                "echo",
                "add",
                {"a": 3, "b": 4},
                transport=transport,
                binding_id="b-99",
            )
            assert getattr(result.content[0], "text", None) == "7"
        finally:
            await mgr.shutdown()

    asyncio.run(run())

    # Exactly one success audit row for this call.
    success_rows = [e for e in events if e.get("result") == "success"]
    assert len(success_rows) == 1
    row = success_rows[0]
    assert row["kind"] == "mcp_tool_call"
    assert row["action"] == "add"
    assert row["agent_id"] == "agent-ok"
    assert row["binding_id"] == "b-99"
    assert row["target"] == "echo"
    assert row["duration_ms"] is not None and row["duration_ms"] >= 0
    assert row["error_kind"] is None


def test_manager_call_tool_timeout_classifies_and_audits():
    """Zero-timeout forces an MCPTimeoutError, and an audit row with
    result=timeout / error_kind=MCPTimeoutError must follow."""
    events: list[dict] = []

    async def run():
        mgr = MCPClientManager(
            agent_id="agent-slow",
            audit_callback=lambda **p: events.append(p),
        )
        transport = StdioTransportSpec(command=_spawn_cmd())
        try:
            with pytest.raises(MCPTimeoutError):
                await mgr.call_tool(
                    "echo",
                    "add",
                    {"a": 1, "b": 2},
                    transport=transport,
                    timeout_seconds=0.0001,
                )
        finally:
            await mgr.shutdown()

    asyncio.run(run())

    timeout_rows = [e for e in events if e.get("result") == "timeout"]
    assert len(timeout_rows) == 1
    assert timeout_rows[0]["error_kind"] == "MCPTimeoutError"


def test_manager_bad_command_classifies_as_server_unavailable():
    """A nonexistent binary → MCPServerUnavailableError, not a raw
    FileNotFoundError. Audit row with result=server_unavailable."""
    events: list[dict] = []

    async def run():
        mgr = MCPClientManager(
            agent_id="agent-bad",
            audit_callback=lambda **p: events.append(p),
        )
        transport = StdioTransportSpec(
            command=["dialekt-nonexistent-binary-xyz"]
        )
        try:
            with pytest.raises(MCPServerUnavailableError):
                await mgr.call_tool(
                    "missing",
                    "anything",
                    {},
                    transport=transport,
                )
        finally:
            await mgr.shutdown()

    asyncio.run(run())

    err_rows = [
        e for e in events if e.get("result") == "server_unavailable"
    ]
    assert len(err_rows) == 1


def test_manager_shutdown_is_idempotent_and_closes_clients():
    async def run():
        mgr = MCPClientManager(agent_id="agent-shut")
        transport = StdioTransportSpec(command=_spawn_cmd())
        await mgr.get_client("echo", transport)
        await mgr.shutdown()
        await mgr.shutdown()  # second call must not raise
        # After shutdown, further get_client raises.
        with pytest.raises(RuntimeError, match="shut down"):
            await mgr.get_client("echo", transport)

    asyncio.run(run())
