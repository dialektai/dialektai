"""Tests for per-tool allow/deny scoping (v0.22 commit 1).

Covers:
- ToolPolicy.permits() semantics: None=all, list=allow-only, deny-wins
- MCPRuntime.invoke_tool blocks denied calls with MCPToolNotAllowed
  before consent or dispatch — never spawns MCP subprocess
- Audit row of kind 'mcp_tool_blocked' is emitted on policy block
- Blocked attempts count toward rate limit (mentor P1 — runaway
  loop hits 60/min ceiling instead of bypass)
- v0.20/v0.21 manifests with no tool_policies arg → behavior unchanged
  (mentor backwards-compat regression test)
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from dialekt.mcp.consent import (
    AutoApproveProvider,
    ConsentDecision,
)
from dialekt.mcp.errors import MCPRateLimitError, MCPToolNotAllowed
from dialekt.mcp.manager import MCPClientManager
from dialekt.mcp.runtime import MCPRuntime, ToolPolicy
from dialekt.mcp.transport import StdioTransportSpec


# ── ToolPolicy unit ──────────────────────────────────────────────────────────


def test_tool_policy_default_permits_everything():
    p = ToolPolicy()
    assert p.permits("any_tool") is True
    assert p.permits("create_issue") is True


def test_tool_policy_allow_only_permits_listed():
    p = ToolPolicy(allow=frozenset({"search_repositories", "get_file_contents"}))
    assert p.permits("search_repositories") is True
    assert p.permits("get_file_contents") is True
    assert p.permits("create_issue") is False  # not in allow


def test_tool_policy_deny_blocks_listed():
    p = ToolPolicy(deny=frozenset({"create_issue", "create_pull_request"}))
    assert p.permits("search_repositories") is True
    assert p.permits("create_issue") is False
    assert p.permits("create_pull_request") is False


def test_tool_policy_deny_wins_over_allow():
    """Mentor ruling §10.A: deny subtracts from allow."""
    p = ToolPolicy(
        allow=frozenset({"create_issue", "create_pull_request", "search_repositories"}),
        deny=frozenset({"create_pull_request"}),
    )
    assert p.permits("create_issue") is True
    assert p.permits("search_repositories") is True
    assert p.permits("create_pull_request") is False  # deny wins


# ── MCPRuntime.invoke_tool gate ──────────────────────────────────────────────


def _make_runtime(tool_policies=None, audit_log=None):
    """Build a runtime against a never-spawned stdio spec.

    The policy gate is supposed to fast-fail BEFORE
    ``self.tool_metadata`` runs, so the test never needs a real MCP
    server — denied calls reach the audit + raise path without ever
    touching ``self._manager.get_client``.
    """
    audit_rows = audit_log if audit_log is not None else []

    def audit_cb(**payload):
        audit_rows.append(payload)
        return SimpleNamespace(json=lambda: {"id": len(audit_rows)})

    spec = StdioTransportSpec(command=["/bin/false"], timeout_seconds=5.0)
    mgr = MCPClientManager(agent_id="test-agent", audit_callback=audit_cb)
    rt = MCPRuntime(
        manager=mgr,
        server_specs={"github": (spec, None, 5.0)},
        consent_provider=AutoApproveProvider(),
        audit_callback=audit_cb,
        autonomy="autonomous",
        agent_id="test-agent",
        tool_policies=tool_policies,
    )
    return rt, audit_rows


def test_invoke_tool_denies_call_in_deny_list_with_audit_row():
    async def run():
        rt, audit = _make_runtime(
            tool_policies={"github": ToolPolicy(deny=frozenset({"create_issue"}))},
        )
        with pytest.raises(MCPToolNotAllowed) as exc:
            await rt.invoke_tool("github", "create_issue", arguments={})
        assert "denied by deny_tools" in str(exc.value)
        kinds = [r["kind"] for r in audit]
        assert "mcp_tool_blocked" in kinds
        # Subprocess was never spawned (manager has no clients).
        assert rt._manager._clients == {}

    asyncio.run(run())


def test_invoke_tool_denies_call_outside_allow_list():
    async def run():
        rt, audit = _make_runtime(
            tool_policies={
                "github": ToolPolicy(allow=frozenset({"search_repositories"}))
            },
        )
        with pytest.raises(MCPToolNotAllowed) as exc:
            await rt.invoke_tool("github", "create_issue", arguments={})
        assert "not in allow_tools" in str(exc.value)
        assert any(r["kind"] == "mcp_tool_blocked" for r in audit)

    asyncio.run(run())


def test_invoke_tool_no_policy_does_not_block():
    """Backwards-compat regression (mentor P2 concern E): manifests
    from v0.20/v0.21 have no allow/deny fields. ws_chat passes no
    tool_policies. Behavior must be identical to pre-v0.22 — every
    call falls through to the existing consent + dispatch flow."""
    async def run():
        rt, _ = _make_runtime(tool_policies=None)
        # The runtime still raises later (no real subprocess), but it
        # must NOT raise MCPToolNotAllowed — it must reach
        # self.tool_metadata, which then fails downstream.
        try:
            await rt.invoke_tool("github", "create_issue", arguments={})
        except MCPToolNotAllowed:
            pytest.fail("v0.20/v0.21 manifest must not be blocked at policy gate")
        except Exception:
            pass  # fine — any other failure means policy gate let it through

    asyncio.run(run())


def test_invoke_tool_empty_policy_dict_does_not_block():
    """Edge: tool_policies={} (empty) → no per-server policies → all
    calls pass the gate. Same regression class as no-arg case."""
    async def run():
        rt, _ = _make_runtime(tool_policies={})
        try:
            await rt.invoke_tool("github", "any_tool", arguments={})
        except MCPToolNotAllowed:
            pytest.fail("empty policy dict must not block")
        except Exception:
            pass

    asyncio.run(run())


def test_blocked_calls_count_toward_rate_limit():
    """Mentor P1: a runaway agent hammering a blocked tool must hit
    the 60/min rate limit and stop emitting mcp_tool_blocked rows
    rather than firehose audit forever."""
    async def run():
        rt, audit = _make_runtime(
            tool_policies={
                "github": ToolPolicy(deny=frozenset({"create_issue"}))
            },
        )
        # Cap the rate limiter low so the test runs fast.
        rt._manager._rate_limit = 5
        for _ in range(5):
            with pytest.raises(MCPToolNotAllowed):
                await rt.invoke_tool("github", "create_issue", arguments={})
        # 6th attempt: rate limit hits FIRST, raises MCPRateLimitError
        # rather than MCPToolNotAllowed. Blocked rows: 5, not 6.
        with pytest.raises(MCPRateLimitError):
            await rt.invoke_tool("github", "create_issue", arguments={})
        blocked_rows = [r for r in audit if r["kind"] == "mcp_tool_blocked"]
        assert len(blocked_rows) == 5

    asyncio.run(run())
