"""Tests for the desktop-sidecar relay config endpoints (Commit 4).

These cover GET/POST /relay/config and POST /relay/test on
``python/server.py`` (the FastAPI sidecar that the Tauri frontend
talks to). The relay-server FastAPI app — a different process —
is covered by test_relay_server.py.

Tests redirect ``DIALEKT_DIR`` and ``RELAY_CONFIG_FILE`` to a tmp
directory so they never touch the real ``~/.dialekt/relay.toml``.
"""
from __future__ import annotations

import sys
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent.parent))


@pytest.fixture
def server_app(tmp_path, monkeypatch):
    """Import server.py with DIALEKT_DIR pointing at a tmp dir.

    server.py reads DIALEKT_DIR / "relay.toml" via module-level globals,
    so we monkeypatch those constants directly after import.
    """
    monkeypatch.setenv("HOME", str(tmp_path))
    import server as srv  # noqa: F401  — module under test
    monkeypatch.setattr(srv, "DIALEKT_DIR", tmp_path / ".dialekt")
    monkeypatch.setattr(
        srv, "RELAY_CONFIG_FILE", tmp_path / ".dialekt" / "relay.toml",
    )
    (tmp_path / ".dialekt").mkdir(parents=True, exist_ok=True)
    return srv


def test_get_returns_defaults_when_file_missing(server_app):
    with TestClient(server_app.app) as tc:
        r = tc.get("/relay/config")
    assert r.status_code == 200
    body = r.json()
    assert body["url"] == "https://gpu-relay.dias.now"
    assert body["enabled"] is False
    assert body["api_key_set"] is False
    assert body["api_key_preview"] == ""


def test_post_persists_to_disk(server_app):
    with TestClient(server_app.app) as tc:
        r = tc.post(
            "/relay/config",
            json={
                "url": "https://gpu-relay.dias.now",
                "api_key": "dlk_relay_secret_token_xyz",
                "enabled": True,
            },
        )
    assert r.status_code == 200
    body = r.json()
    assert body["enabled"] is True
    assert body["api_key_set"] is True
    assert body["api_key_preview"].startswith("dlk_")
    assert body["api_key_preview"].endswith("_xyz")

    # Round-trip via fresh load.
    cfg = server_app.load_relay_config()
    assert cfg["api_key"] == "dlk_relay_secret_token_xyz"
    assert cfg["enabled"] is True


def test_post_with_empty_api_key_preserves_existing(server_app):
    """The UI sends api_key only when rotating. Empty string must not
    wipe the saved key."""
    server_app.save_relay_config({
        "url": "https://gpu-relay.dias.now",
        "api_key": "dlk_relay_keep_me",
        "enabled": True,
    })
    with TestClient(server_app.app) as tc:
        r = tc.post(
            "/relay/config",
            json={
                "url": "https://gpu-relay.dias.now",
                "api_key": "",
                "enabled": False,
            },
        )
    assert r.status_code == 200
    cfg = server_app.load_relay_config()
    assert cfg["api_key"] == "dlk_relay_keep_me"
    assert cfg["enabled"] is False


def test_post_rotates_api_key_when_provided(server_app):
    server_app.save_relay_config({
        "url": "https://gpu-relay.dias.now",
        "api_key": "dlk_relay_old",
        "enabled": True,
    })
    with TestClient(server_app.app) as tc:
        r = tc.post(
            "/relay/config",
            json={"api_key": "dlk_relay_new", "url": "https://gpu-relay.dias.now", "enabled": True},
        )
    assert r.status_code == 200
    assert server_app.load_relay_config()["api_key"] == "dlk_relay_new"


def test_post_rejects_quotes_safely(server_app):
    """A URL containing a literal double-quote should round-trip
    intact via TOML escaping."""
    weird_url = 'https://gpu-relay.dias.now/"path"'
    server_app.save_relay_config({
        "url": weird_url, "api_key": "x", "enabled": True,
    })
    cfg = server_app.load_relay_config()
    assert cfg["url"] == weird_url


def test_test_endpoint_reports_network_error(server_app):
    with TestClient(server_app.app) as tc:
        r = tc.post(
            "/relay/test",
            json={"url": "http://127.0.0.1:1", "api_key": ""},
        )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert "network error" in body["error"]


def test_test_endpoint_uses_saved_url_when_omitted(server_app, monkeypatch):
    server_app.save_relay_config({
        "url": "http://127.0.0.1:1",  # always-failing
        "api_key": "",
        "enabled": False,
    })
    with TestClient(server_app.app) as tc:
        r = tc.post("/relay/test", json={})
    assert r.status_code == 200
    body = r.json()
    assert body["url"] == "http://127.0.0.1:1"
    assert body["ok"] is False  # connection refused
