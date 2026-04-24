"""Tests for dialekt.mcp.secrets_resolver.

The resolver reaches into ``dialekt.secrets.get_secret`` so tests
monkeypatch that function to inject a predictable keyring for each
case. No real keyring is touched.
"""
import pytest

from dialekt.mcp.errors import MCPConfigError
from dialekt.mcp.secrets_resolver import (
    has_unresolved_refs,
    keyring_key,
    resolve_env,
    resolve_secret_refs,
)


def _patched_secret_store(
    monkeypatch: pytest.MonkeyPatch, mapping: dict[str, str]
) -> None:
    """Wire dialekt.mcp.secrets_resolver.get_secret to a dict lookup."""
    monkeypatch.setattr(
        "dialekt.mcp.secrets_resolver.get_secret",
        lambda name: mapping.get(name),
    )


def test_keyring_key_uses_mcp_prefix_and_server_segment():
    assert keyring_key("github", "github_token") == "mcp.github.github_token"
    assert keyring_key("jira", "bearer") == "mcp.jira.bearer"


def test_resolve_plain_string_untouched():
    assert (
        resolve_secret_refs("literal value, no refs", server_name="github")
        == "literal value, no refs"
    )


def test_resolve_single_ref(monkeypatch):
    _patched_secret_store(
        monkeypatch, {"mcp.github.github_token": "ghp_xyz"}
    )
    assert (
        resolve_secret_refs("${secrets.github_token}", server_name="github")
        == "ghp_xyz"
    )


def test_resolve_ref_embedded_in_longer_string(monkeypatch):
    _patched_secret_store(
        monkeypatch, {"mcp.github.github_token": "ghp_xyz"}
    )
    result = resolve_secret_refs(
        "Bearer ${secrets.github_token}!", server_name="github"
    )
    assert result == "Bearer ghp_xyz!"


def test_resolve_multiple_refs_in_one_string(monkeypatch):
    _patched_secret_store(
        monkeypatch,
        {
            "mcp.internal.user": "alice",
            "mcp.internal.pass": "wonderland",
        },
    )
    result = resolve_secret_refs(
        "${secrets.user}:${secrets.pass}@internal",
        server_name="internal",
    )
    assert result == "alice:wonderland@internal"


def test_resolve_missing_secret_raises_config_error(monkeypatch):
    _patched_secret_store(monkeypatch, {})  # empty keyring
    with pytest.raises(MCPConfigError) as exc_info:
        resolve_secret_refs(
            "${secrets.github_token}", server_name="github"
        )
    msg = str(exc_info.value)
    assert "github" in msg
    assert "github_token" in msg
    assert "mcp.github.github_token" in msg  # points user at the exact key


def test_resolve_uses_server_name_in_namespace(monkeypatch):
    """A ref named `github_token` on server `slack` maps to a
    SLACK-namespaced keyring entry, not a github one."""
    _patched_secret_store(
        monkeypatch,
        {
            "mcp.github.api_key": "github-value",
            "mcp.slack.api_key": "slack-value",
        },
    )
    assert (
        resolve_secret_refs("${secrets.api_key}", server_name="github")
        == "github-value"
    )
    assert (
        resolve_secret_refs("${secrets.api_key}", server_name="slack")
        == "slack-value"
    )


def test_resolve_env_maps_every_value(monkeypatch):
    _patched_secret_store(
        monkeypatch,
        {"mcp.gh.github_token": "ghp_xyz"},
    )
    env = {
        "GITHUB_TOKEN": "${secrets.github_token}",
        "DEBUG": "1",
        "LOG_LEVEL": "${secrets.github_token}/debug",
    }
    resolved = resolve_env(env, server_name="gh")
    assert resolved == {
        "GITHUB_TOKEN": "ghp_xyz",
        "DEBUG": "1",
        "LOG_LEVEL": "ghp_xyz/debug",
    }


def test_resolve_env_preserves_keys(monkeypatch):
    _patched_secret_store(monkeypatch, {})
    resolved = resolve_env({"A": "1", "B": "2"}, server_name="x")
    assert resolved == {"A": "1", "B": "2"}


def test_has_unresolved_refs_detects_placeholder():
    assert has_unresolved_refs("${secrets.token}") is True
    assert has_unresolved_refs("Bearer ${secrets.t}") is True
    assert has_unresolved_refs("plain string") is False
    assert has_unresolved_refs("") is False


def test_ref_with_dotted_name_resolves(monkeypatch):
    """Secret names allow dots (for further sub-namespacing if the UI
    exposes it). The regex pattern permits [A-Za-z0-9_.-]."""
    _patched_secret_store(
        monkeypatch, {"mcp.svc.api.token.v2": "value"}
    )
    assert (
        resolve_secret_refs("${secrets.api.token.v2}", server_name="svc")
        == "value"
    )
