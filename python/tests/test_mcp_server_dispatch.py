"""Tests for MCPServer's dispatch plumbing — key binding, tool-allow
decisions, rate limiter integration, audit emit.

Tool categories are inferred from the tool name via the registry in
server.py; these tests pin that mapping so tool modules in later
commits can safely name themselves per the pattern.
"""
import pytest

from dialekt.mcp.server import MCPServer, ServerConfig
from dialekt.mcp.server.auth import RateLimitExceeded
from dialekt.mcp.server.config import ApiKey


def _server(config=None, audit_callback=None, clock=None) -> MCPServer:
    if config is None:
        config = ServerConfig()
    kwargs = {"audit_callback": audit_callback}
    if clock is not None:
        kwargs["clock"] = clock
    return MCPServer(config, **kwargs)


# ---------------------------------------------------------------------------
# bind_active_key.
# ---------------------------------------------------------------------------


def test_active_key_none_until_bound():
    s = _server()
    assert s.active_key is None


def test_bind_active_key_stores():
    s = _server()
    key = ApiKey(id="claude-desktop", value="x" * 32)
    s.bind_active_key(key)
    assert s.active_key is key


def test_bind_active_key_refuses_rebind():
    s = _server()
    s.bind_active_key(ApiKey(id="first", value="x" * 32))
    with pytest.raises(RuntimeError, match="already set"):
        s.bind_active_key(ApiKey(id="second", value="y" * 32))


# ---------------------------------------------------------------------------
# is_tool_allowed — category gate.
# ---------------------------------------------------------------------------


def test_tool_allowed_when_category_enabled():
    s = _server(ServerConfig(enabled_categories=["database"]))
    assert s.is_tool_allowed("dialekt_list_connections") is True
    assert s.is_tool_allowed("dialekt_query_database") is True


def test_tool_denied_when_category_disabled():
    s = _server(ServerConfig(enabled_categories=["file"]))
    assert s.is_tool_allowed("dialekt_list_connections") is False


def test_unknown_tool_allowed_when_no_key_restriction():
    """Tools that don't match any category fragment (e.g. a future
    tool we haven't taught the inferrer about) default to allowed
    unless a per-key allow-list rejects them."""
    s = _server()
    assert s.is_tool_allowed("dialekt_unknown_future_tool") is True


# ---------------------------------------------------------------------------
# is_tool_allowed — per-key enabled_tools gate.
# ---------------------------------------------------------------------------


def test_per_key_allow_list_restricts():
    s = _server()
    s.bind_active_key(ApiKey(
        id="scoped",
        value="x" * 32,
        enabled_tools=["dialekt_list_connections"],
    ))
    assert s.is_tool_allowed("dialekt_list_connections") is True
    assert s.is_tool_allowed("dialekt_query_database") is False


def test_per_key_empty_allow_list_blocks_everything():
    """An explicit empty list means "allow nothing" — distinct from
    the None default which means "all tools in enabled_categories"."""
    s = _server()
    s.bind_active_key(ApiKey(
        id="nothing",
        value="x" * 32,
        enabled_tools=[],
    ))
    assert s.is_tool_allowed("dialekt_list_connections") is False


def test_per_key_none_allow_list_falls_through_to_category_gate():
    s = _server(ServerConfig(enabled_categories=["file"]))
    s.bind_active_key(ApiKey(id="open", value="x" * 32))  # enabled_tools=None
    assert s.is_tool_allowed("dialekt_read_file") is True
    assert s.is_tool_allowed("dialekt_query_database") is False


# ---------------------------------------------------------------------------
# Rate limiter integration.
# ---------------------------------------------------------------------------


def test_check_rate_limit_proxies_to_limiter():
    now = [0.0]
    s = _server(ServerConfig(rate_limit_per_minute=2), clock=lambda: now[0])
    s.check_rate_limit()
    s.check_rate_limit()
    with pytest.raises(RateLimitExceeded):
        s.check_rate_limit()


def test_rate_limiter_uses_server_config_value():
    s = _server(ServerConfig(rate_limit_per_minute=7))
    # Internal check — verifies wiring without touching private API
    # in a brittle way.
    for _ in range(7):
        s.check_rate_limit()
    with pytest.raises(RateLimitExceeded):
        s.check_rate_limit()


# ---------------------------------------------------------------------------
# emit_audit.
# ---------------------------------------------------------------------------


def test_emit_audit_fills_defaults():
    """kind defaults to mcp_server_tool_call, target defaults to key id."""
    events: list[dict] = []
    s = _server(audit_callback=lambda **p: events.append(p))
    s.bind_active_key(ApiKey(id="claude-desktop", value="x" * 32))
    s.emit_audit(action="dialekt_list_connections", result="success")
    assert events[0]["kind"] == "mcp_server_tool_call"
    assert events[0]["target"] == "claude-desktop"
    assert events[0]["action"] == "dialekt_list_connections"
    assert events[0]["result"] == "success"


def test_emit_audit_caller_overrides_defaults():
    events: list[dict] = []
    s = _server(audit_callback=lambda **p: events.append(p))
    s.bind_active_key(ApiKey(id="a", value="x" * 32))
    s.emit_audit(
        kind="custom_kind",
        action="x",
        result="success",
        target="not-the-key-id",
    )
    assert events[0]["kind"] == "custom_kind"
    assert events[0]["target"] == "not-the-key-id"


def test_emit_audit_no_callback_is_noop():
    s = _server()  # no audit_callback
    # Must not raise.
    s.emit_audit(action="x", result="success")


def test_emit_audit_callback_errors_are_swallowed():
    def broken(**p):
        raise RuntimeError("simulated audit sink failure")

    s = _server(audit_callback=broken)
    s.emit_audit(action="x", result="success")  # does not propagate
