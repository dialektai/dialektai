"""Tests for dialekt.mcp.server.cli — argv parsing, precondition
checks, exit codes.

The run loop itself (run_stdio) is not invoked — that would block on
actual MCP protocol traffic. Tests stop short of entering the loop
and verify the CLI reaches the right guard-rail outcome for each
input scenario.
"""
import os

import pytest

from dialekt.mcp.server.cli import (
    EXIT_AUTH,
    EXIT_BACKEND_UNREACHABLE,
    EXIT_CONFIG,
    EXIT_GENERIC,
    EXIT_OK,
    _parse_args,
    main,
)


# ---------------------------------------------------------------------------
# Argument parsing.
# ---------------------------------------------------------------------------


def test_parse_args_all_flags():
    args = _parse_args([
        "--api-key", "secret-key-at-least-16-chars",
        "--backend", "http://custom:9999",
        "--config", "/tmp/custom.toml",
    ])
    assert args.api_key == "secret-key-at-least-16-chars"
    assert args.backend == "http://custom:9999"
    assert args.config == "/tmp/custom.toml"
    assert args.dev is False


def test_parse_args_dev_flag():
    args = _parse_args(["--dev"])
    assert args.dev is True


def test_parse_args_defaults():
    args = _parse_args([])
    assert args.api_key is None
    assert args.backend is None
    assert args.config is None
    assert args.dev is False


# ---------------------------------------------------------------------------
# Backend-unreachable precondition.
# ---------------------------------------------------------------------------


def test_main_exits_when_backend_unreachable(tmp_path, monkeypatch, capsys):
    """--backend pointed at an unreachable port → EXIT_BACKEND_UNREACHABLE
    with a helpful stderr message."""
    monkeypatch.delenv("DIALEKT_MCP_API_KEY", raising=False)
    monkeypatch.setenv("DIALEKT_MCP_CONFIG_PATH", str(tmp_path / "none.toml"))

    # Port 1 — reserved, TCP connect almost always fails.
    code = main(["--backend", "http://127.0.0.1:1", "--api-key", "x" * 32])
    assert code == EXIT_BACKEND_UNREACHABLE

    err = capsys.readouterr().err
    assert "cannot reach dialekt backend" in err
    assert "DIALEKT_BACKEND_URL" in err  # hint shown


# ---------------------------------------------------------------------------
# Auth failure exit.
# ---------------------------------------------------------------------------


def test_main_exits_when_api_key_missing(tmp_path, monkeypatch, capsys):
    """Backend is fake-reachable via monkeypatch but no api-key provided."""
    # Inject a backend that exists so we reach the auth step.
    monkeypatch.setattr(
        "dialekt.mcp.server.cli._ping_backend",
        lambda *args, **kw: True,
    )
    monkeypatch.setenv("DIALEKT_MCP_CONFIG_PATH", str(tmp_path / "none.toml"))
    monkeypatch.delenv("DIALEKT_MCP_API_KEY", raising=False)

    code = main([])
    assert code == EXIT_AUTH
    err = capsys.readouterr().err
    assert "no API key" in err


def test_main_exits_when_api_key_unknown(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(
        "dialekt.mcp.server.cli._ping_backend",
        lambda *args, **kw: True,
    )
    # Config with one key; caller provides a different key.
    cfg = tmp_path / "c.toml"
    cfg.write_text("""
[server]
api_keys = [{id = "known", value = "known-value-long-enough-to-pass"}]
""")
    monkeypatch.setenv("DIALEKT_MCP_CONFIG_PATH", str(cfg))
    monkeypatch.delenv("DIALEKT_MCP_API_KEY", raising=False)

    code = main(["--api-key", "wrong-key-but-long-enough-chars"])
    assert code == EXIT_AUTH
    err = capsys.readouterr().err
    assert "not recognised" in err


def test_main_accepts_valid_key_and_starts_server(tmp_path, monkeypatch):
    """Happy path up to the point of entering run_stdio — we stop
    there to avoid blocking. ``run_stdio`` is monkeypatched to return
    immediately."""
    monkeypatch.setattr(
        "dialekt.mcp.server.cli._ping_backend",
        lambda *args, **kw: True,
    )
    monkeypatch.setattr(
        "dialekt.mcp.server.server.MCPServer.run_stdio",
        lambda self: None,
    )

    cfg = tmp_path / "c.toml"
    cfg.write_text("""
[server]
api_keys = [{id = "ok", value = "valid-key-long-enough-to-satisfy"}]
""")
    monkeypatch.setenv("DIALEKT_MCP_CONFIG_PATH", str(cfg))
    monkeypatch.delenv("DIALEKT_MCP_API_KEY", raising=False)

    code = main(["--api-key", "valid-key-long-enough-to-satisfy"])
    assert code == EXIT_OK


# ---------------------------------------------------------------------------
# --dev bypass.
# ---------------------------------------------------------------------------


def test_dev_flag_bypasses_auth(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "dialekt.mcp.server.cli._ping_backend",
        lambda *args, **kw: True,
    )
    monkeypatch.setattr(
        "dialekt.mcp.server.server.MCPServer.run_stdio",
        lambda self: None,
    )
    monkeypatch.setenv("DIALEKT_MCP_CONFIG_PATH", str(tmp_path / "none.toml"))
    monkeypatch.delenv("DIALEKT_MCP_API_KEY", raising=False)

    code = main(["--dev"])
    assert code == EXIT_OK


# ---------------------------------------------------------------------------
# Env-var precedence.
# ---------------------------------------------------------------------------


def test_env_api_key_works_when_flag_absent(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "dialekt.mcp.server.cli._ping_backend",
        lambda *args, **kw: True,
    )
    monkeypatch.setattr(
        "dialekt.mcp.server.server.MCPServer.run_stdio",
        lambda self: None,
    )
    cfg = tmp_path / "c.toml"
    cfg.write_text("""
[server]
api_keys = [{id = "e", value = "env-sourced-api-key-safely-long"}]
""")
    monkeypatch.setenv("DIALEKT_MCP_CONFIG_PATH", str(cfg))
    monkeypatch.setenv("DIALEKT_MCP_API_KEY", "env-sourced-api-key-safely-long")

    code = main([])  # no --api-key arg
    assert code == EXIT_OK


# ---------------------------------------------------------------------------
# Argparse errors.
# ---------------------------------------------------------------------------


def test_unknown_flag_exits_via_argparse(monkeypatch):
    """argparse raises SystemExit with code 2 by default on bad args."""
    with pytest.raises(SystemExit):
        _parse_args(["--unknown-flag"])
