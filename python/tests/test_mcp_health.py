"""Tests for MCPHealthRegistry — v0.26 process resilience commit 1.
Mentor pass-1 P1 coverage: clean cycle, idempotence, callback failure
isolation, lock contention. Manager wire-in covered by integration in
test_mcp_manager + test_mcp_e2e_filesystem (no regressions, +5 LOC)."""
import asyncio

import pytest

from dialekt.mcp.health import MCPHealthRegistry


@pytest.mark.asyncio
async def test_clean_cycle_healthy_crashed_healthy():
    reg = MCPHealthRegistry()
    await reg.mark_healthy("a"); assert reg.status("a").status == "healthy"
    await reg.mark_crashed("a", "X")
    assert reg.status("a").status == "crashed" and reg.status("a").error == "X"
    await reg.mark_healthy("a"); assert reg.status("a").status == "healthy"


@pytest.mark.asyncio
async def test_redundant_mark_healthy_does_not_persist():
    """First-healthy and same-state pings must not fire persist —
    manual [Test] outcome stays authoritative in mcp_servers row."""
    persisted = []
    async def cb(n, s, e): persisted.append((n, s, e))
    reg = MCPHealthRegistry(persist_callback=cb)
    await reg.mark_healthy("a"); await reg.mark_healthy("a")
    assert persisted == []


@pytest.mark.asyncio
async def test_mark_crashed_always_wins_and_re_stamps():
    persisted = []
    async def cb(n, s, e): persisted.append((n, s, e))
    reg = MCPHealthRegistry(persist_callback=cb)
    await reg.mark_healthy("a")
    await reg.mark_crashed("a", "X"); await reg.mark_crashed("a", "Y")
    assert [s for (_, s, _) in persisted] == ["crashed", "crashed"]
    assert reg.status("a").error == "Y"


@pytest.mark.asyncio
async def test_recovery_clears_prior_crashed_via_persist():
    persisted = []
    async def cb(n, s, e): persisted.append((n, s, e))
    reg = MCPHealthRegistry(persist_callback=cb)
    await reg.mark_crashed("a", "X"); persisted.clear()
    await reg.mark_healthy("a")
    assert persisted == [("a", "healthy", None)]


@pytest.mark.asyncio
async def test_callback_raise_does_not_propagate():
    """P1 mentor pass 1: persist_callback raising must NOT leak into
    mark_* callers (which run inside MCPClientManager.call_tool)."""
    async def boom(n, s, e): raise ValueError("simulated DB failure")
    reg = MCPHealthRegistry(persist_callback=boom)
    await reg.mark_crashed("a", "X")
    await reg.mark_healthy("a")
    assert reg.status("a").status == "healthy"


@pytest.mark.asyncio
async def test_concurrent_mark_crashed_no_corruption():
    reg = MCPHealthRegistry()
    await asyncio.gather(reg.mark_crashed("a", "X"), reg.mark_crashed("a", "Y"))
    assert reg.status("a").status == "crashed"
    assert reg.status("a").error in ("X", "Y")


@pytest.mark.asyncio
async def test_status_returns_none_for_unknown_server():
    assert MCPHealthRegistry().status("never-touched") is None
