"""Tests for dialekt.mcp.server.config — TOML load + env overrides."""
from pathlib import Path

import pytest

from dialekt.mcp.server.config import (
    DEFAULT_BACKEND_URL,
    DEFAULT_CONFIG_PATH,
    DEFAULT_LOG_LEVEL,
    DEFAULT_RATE_LIMIT,
    ApiKey,
    ServerConfig,
    load_config,
)


# ---------------------------------------------------------------------------
# Defaults.
# ---------------------------------------------------------------------------


def test_defaults_when_file_missing(tmp_path, monkeypatch):
    """Missing config file → all defaults, empty api_keys."""
    # Drop any leaking env so defaults apply.
    for var in (
        "DIALEKT_MCP_CONFIG_PATH",
        "DIALEKT_BACKEND_URL",
        "DIALEKT_MCP_LOG_LEVEL",
        "DIALEKT_MCP_API_KEY",
    ):
        monkeypatch.delenv(var, raising=False)

    config = load_config(tmp_path / "does-not-exist.toml")
    assert config.api_keys == []
    assert config.rate_limit_per_minute == DEFAULT_RATE_LIMIT
    assert config.backend_url == DEFAULT_BACKEND_URL
    assert config.log_level == DEFAULT_LOG_LEVEL
    assert config.allowed_file_roots == []
    assert config.transport.stdio.enabled is True
    assert config.transport.http.enabled is False


def test_enabled_categories_default_is_full_set():
    config = ServerConfig()
    assert set(config.enabled_categories) == {
        "database",
        "file",
        "agent",
        "http",
        "rss",
        "bitrix",
        "instagram",
        "visual",
        "web_crawl",
        "calendar",
        "scheduling",
        "cdn",
    }


def test_unknown_category_rejected():
    with pytest.raises(ValueError, match="Unknown tool categories"):
        ServerConfig(enabled_categories=["database", "banana"])


# ---------------------------------------------------------------------------
# TOML parsing.
# ---------------------------------------------------------------------------


def _write_toml(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "mcp-server.toml"
    p.write_text(body)
    return p


def test_loads_api_keys_from_toml(tmp_path, monkeypatch):
    monkeypatch.delenv("DIALEKT_MCP_API_KEY", raising=False)
    p = _write_toml(tmp_path, """
[server]
api_keys = [
    {id = "claude-desktop", value = "sekret-one-long-enough-to-pass-validation"},
    {id = "cursor",         value = "sekret-two-long-enough-to-pass-validation"},
]
""")
    config = load_config(p)
    assert len(config.api_keys) == 2
    assert config.api_keys[0].id == "claude-desktop"
    assert config.api_keys[0].enabled_tools is None
    assert config.api_keys[1].id == "cursor"


def test_per_key_enabled_tools(tmp_path, monkeypatch):
    monkeypatch.delenv("DIALEKT_MCP_API_KEY", raising=False)
    p = _write_toml(tmp_path, """
[server]
api_keys = [
    {id = "scoped", value = "sekret-scoped-value-long-enough", enabled_tools = ["dialekt_list_connections"]},
]
""")
    config = load_config(p)
    assert config.api_keys[0].enabled_tools == ["dialekt_list_connections"]


def test_api_key_id_pattern_enforced():
    with pytest.raises(ValueError):
        ApiKey(id="Bad Id With Spaces", value="sekret-long-enough-to-pass")


def test_api_key_value_min_length():
    with pytest.raises(ValueError):
        ApiKey(id="short", value="tiny")  # < 16 chars


def test_allowed_file_roots_expanded_and_absolutised(tmp_path, monkeypatch):
    monkeypatch.delenv("DIALEKT_MCP_API_KEY", raising=False)
    p = _write_toml(tmp_path, f"""
[server]
allowed_file_roots = ["{tmp_path}/shared", "~"]
""")
    config = load_config(p)
    # Both become absolute; ~ gets expanded.
    for root in config.allowed_file_roots:
        assert root.startswith("/"), f"not absolute: {root!r}"
    assert any(r.endswith("/shared") for r in config.allowed_file_roots)


def test_transport_http_disabled_by_default(tmp_path, monkeypatch):
    monkeypatch.delenv("DIALEKT_MCP_API_KEY", raising=False)
    p = _write_toml(tmp_path, "[server]\n")
    config = load_config(p)
    assert config.transport.http.enabled is False
    assert config.transport.http.port == 8766


# ---------------------------------------------------------------------------
# API key lookup.
# ---------------------------------------------------------------------------


def test_has_api_key_matches_by_value():
    config = ServerConfig(
        api_keys=[
            ApiKey(id="a", value="value-a-with-enough-length-to-pass"),
            ApiKey(id="b", value="value-b-with-enough-length-to-pass"),
        ]
    )
    match = config.has_api_key("value-b-with-enough-length-to-pass")
    assert match is not None and match.id == "b"
    assert config.has_api_key("wrong-value-not-matching-anything") is None


def test_has_api_key_constant_time_safe():
    """Smoke: the lookup uses secrets.compare_digest — verify via
    round-trip. Real timing-attack verification needs statistical
    analysis we don't run here."""
    import secrets as _secrets

    config = ServerConfig(
        api_keys=[ApiKey(id="a", value="value-a-with-enough-length-to-pass")]
    )
    assert config.has_api_key("value-a-with-enough-length-to-pass").id == "a"
    # Function still works for non-match.
    assert config.has_api_key(_secrets.token_urlsafe(32)) is None


# ---------------------------------------------------------------------------
# Environment-variable overrides.
# ---------------------------------------------------------------------------


def test_env_override_backend_url(tmp_path, monkeypatch):
    monkeypatch.setenv("DIALEKT_BACKEND_URL", "http://override:9999")
    monkeypatch.delenv("DIALEKT_MCP_API_KEY", raising=False)
    config = load_config(tmp_path / "missing.toml")
    assert config.backend_url == "http://override:9999"


def test_env_override_log_level(tmp_path, monkeypatch):
    monkeypatch.setenv("DIALEKT_MCP_LOG_LEVEL", "debug")
    monkeypatch.delenv("DIALEKT_MCP_API_KEY", raising=False)
    config = load_config(tmp_path / "missing.toml")
    assert config.log_level == "DEBUG"


def test_env_injected_api_key_appended_with_env_id(tmp_path, monkeypatch):
    """DIALEKT_MCP_API_KEY → appends an ApiKey(id='env', value=...)."""
    monkeypatch.setenv(
        "DIALEKT_MCP_API_KEY", "env-injected-api-key-at-least-16-chars"
    )
    config = load_config(tmp_path / "missing.toml")
    assert len(config.api_keys) == 1
    assert config.api_keys[0].id == "env"
    assert config.api_keys[0].value == "env-injected-api-key-at-least-16-chars"


def test_env_override_can_be_disabled(tmp_path, monkeypatch):
    """apply_env_overrides=False leaves env alone — test determinism."""
    monkeypatch.setenv("DIALEKT_BACKEND_URL", "http://should-not-apply:1")
    monkeypatch.setenv("DIALEKT_MCP_API_KEY", "should-not-appear-in-list-16chr")
    config = load_config(tmp_path / "missing.toml", apply_env_overrides=False)
    assert config.backend_url == DEFAULT_BACKEND_URL
    assert config.api_keys == []


# ---------------------------------------------------------------------------
# DIALEKT_MCP_CONFIG_PATH env.
# ---------------------------------------------------------------------------


def test_env_config_path_wins_when_arg_is_none(tmp_path, monkeypatch):
    p = _write_toml(tmp_path, '[server]\nrate_limit_per_minute = 42\n')
    monkeypatch.setenv("DIALEKT_MCP_CONFIG_PATH", str(p))
    monkeypatch.delenv("DIALEKT_MCP_API_KEY", raising=False)
    config = load_config()
    assert config.rate_limit_per_minute == 42


def test_explicit_path_wins_over_env(tmp_path, monkeypatch):
    """If the caller passes a path, DIALEKT_MCP_CONFIG_PATH is ignored."""
    explicit = tmp_path / "explicit.toml"
    explicit.write_text('[server]\nrate_limit_per_minute = 7\n')
    ignored = tmp_path / "ignored.toml"
    ignored.write_text('[server]\nrate_limit_per_minute = 999\n')

    monkeypatch.setenv("DIALEKT_MCP_CONFIG_PATH", str(ignored))
    monkeypatch.delenv("DIALEKT_MCP_API_KEY", raising=False)
    config = load_config(explicit)
    assert config.rate_limit_per_minute == 7


def test_default_config_path_constant():
    assert DEFAULT_CONFIG_PATH.name == "mcp-server.toml"
    assert DEFAULT_CONFIG_PATH.parent.name == ".dialekt"
