"""Tests for the per-agent secrets endpoints."""
from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest


@pytest.fixture(scope="module")
def client():
    """Spin up a TestClient against a temp ``~/.dialekt`` so the
    test never touches the user's real DB or keychain.

    Mirrors the pattern in test_reload_schema.py / test_branding.py
    so the suite stays consistent.
    """
    from fastapi.testclient import TestClient
    import server as srv

    # In-memory dict stand-in for the OS keychain — set/get/delete go
    # through this instead of poking gnome-keyring etc. on CI.
    fake_keychain: dict[str, str] = {}

    def _set(name, value):
        fake_keychain[name] = value

    def _get(name):
        return fake_keychain.get(name)

    def _delete(name):
        fake_keychain.pop(name, None)

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp) / ".dialekt"
        tmp_dir.mkdir(parents=True)

        original_db = srv.DB_PATH
        original_cfg = srv.SETTINGS_FILE
        original_ddir = srv.DIALEKT_DIR

        srv.DB_PATH = tmp_dir / "dialekt.db"
        srv.SETTINGS_FILE = tmp_dir / "config.json"
        srv.DIALEKT_DIR = tmp_dir

        with patch.object(srv, "set_secret", _set), \
             patch.object(srv, "get_secret", _get), \
             patch.object(srv, "delete_secret", _delete):
            with TestClient(srv.app, raise_server_exceptions=True) as c:
                c.fake_keychain = fake_keychain  # type: ignore[attr-defined]
                yield c

        srv.DB_PATH = original_db
        srv.SETTINGS_FILE = original_cfg
        srv.DIALEKT_DIR = original_ddir


def _create_agent(client) -> str:
    r = client.post(
        "/agents",
        json={
            "name": "test-agent",
            "description": "fixture",
            "system_prompt": "you are a test",
        },
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_post_secrets_writes_to_keychain_and_index(client):
    agent_id = _create_agent(client)
    r = client.post(
        f"/agents/{agent_id}/secrets",
        json={
            "secrets": {
                "bitrix_webhook_url": "https://portal.bitrix24.kz/rest/1/abc",
                "instagram_access_token": "tok-xyz",
            }
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body["written"]) == {"bitrix_webhook_url", "instagram_access_token"}

    # Keychain has namespaced entries.
    kc = client.fake_keychain
    assert kc[f"agent:{agent_id}:bitrix_webhook_url"] == "https://portal.bitrix24.kz/rest/1/abc"
    assert kc[f"agent:{agent_id}:instagram_access_token"] == "tok-xyz"


def test_get_secrets_returns_names_only(client):
    agent_id = _create_agent(client)
    client.post(
        f"/agents/{agent_id}/secrets",
        json={"secrets": {"bitrix_webhook_url": "secret-value-1234"}},
    )
    r = client.get(f"/agents/{agent_id}/secrets")
    assert r.status_code == 200
    body = r.json()
    assert body["agent_id"] == agent_id
    names = [s["name"] for s in body["secrets"]]
    assert "bitrix_webhook_url" in names
    # Values never echoed.
    serialised = r.text
    assert "secret-value-1234" not in serialised


def test_post_rejects_invalid_name(client):
    agent_id = _create_agent(client)
    r = client.post(
        f"/agents/{agent_id}/secrets",
        json={"secrets": {"bad name with spaces": "x"}},
    )
    assert r.status_code == 400


def test_post_rejects_empty_value(client):
    agent_id = _create_agent(client)
    r = client.post(
        f"/agents/{agent_id}/secrets",
        json={"secrets": {"valid_name": ""}},
    )
    assert r.status_code == 400


def test_post_rejects_empty_secrets_object(client):
    agent_id = _create_agent(client)
    r = client.post(f"/agents/{agent_id}/secrets", json={"secrets": {}})
    assert r.status_code == 400


def test_post_unknown_agent_404(client):
    r = client.post(
        "/agents/does-not-exist/secrets",
        json={"secrets": {"valid_name": "x"}},
    )
    assert r.status_code == 404


def test_post_is_idempotent_upsert(client):
    agent_id = _create_agent(client)
    client.post(
        f"/agents/{agent_id}/secrets",
        json={"secrets": {"my_secret": "v1"}},
    )
    client.post(
        f"/agents/{agent_id}/secrets",
        json={"secrets": {"my_secret": "v2"}},
    )
    # Latest value wins; index has exactly one row.
    assert client.fake_keychain[f"agent:{agent_id}:my_secret"] == "v2"
    r = client.get(f"/agents/{agent_id}/secrets")
    names = [s["name"] for s in r.json()["secrets"]]
    assert names.count("my_secret") == 1


def test_delete_removes_from_keychain_and_index(client):
    agent_id = _create_agent(client)
    client.post(
        f"/agents/{agent_id}/secrets",
        json={"secrets": {"to_delete": "v"}},
    )
    r = client.delete(f"/agents/{agent_id}/secrets/to_delete")
    assert r.status_code == 204

    assert f"agent:{agent_id}:to_delete" not in client.fake_keychain
    rg = client.get(f"/agents/{agent_id}/secrets")
    names = [s["name"] for s in rg.json()["secrets"]]
    assert "to_delete" not in names


def test_delete_idempotent_for_missing(client):
    agent_id = _create_agent(client)
    r = client.delete(f"/agents/{agent_id}/secrets/never_existed")
    assert r.status_code == 204


def test_delete_rejects_invalid_name(client):
    agent_id = _create_agent(client)
    # Slashes in the name turn into a path-traversal attempt; FastAPI
    # routing won't match (404), which is just as safe as the 400 our
    # handler would emit. Either is acceptable as long as the handler
    # NEVER deletes a sibling agent's secret.
    r = client.delete(f"/agents/{agent_id}/secrets/bad%2Fname")
    assert r.status_code in (400, 404)
    # And a name with disallowed characters that DOES match the route
    # gets a clean 400 from our validator.
    r2 = client.delete(f"/agents/{agent_id}/secrets/bad name")
    assert r2.status_code == 400


def test_secrets_per_agent_isolation(client):
    a = _create_agent(client)
    b = _create_agent(client)
    client.post(f"/agents/{a}/secrets", json={"secrets": {"my_token": "A"}})
    client.post(f"/agents/{b}/secrets", json={"secrets": {"my_token": "B"}})

    assert client.fake_keychain[f"agent:{a}:my_token"] == "A"
    assert client.fake_keychain[f"agent:{b}:my_token"] == "B"

    a_names = [
        s["name"] for s in client.get(f"/agents/{a}/secrets").json()["secrets"]
    ]
    b_names = [
        s["name"] for s in client.get(f"/agents/{b}/secrets").json()["secrets"]
    ]
    assert a_names == ["my_token"]
    assert b_names == ["my_token"]
