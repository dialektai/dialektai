"""Tests for /mcp-servers CRUD + /test endpoints.

Uses FastAPI TestClient with a temp SQLite DB. Keyring is stubbed
with an in-memory dict so no real OS keychain is touched.
"""
import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def keyring_store(monkeypatch):
    """In-memory keyring that mimics dialekt.secrets."""
    store: dict[str, str] = {}

    def fake_set(name: str, value: str) -> None:
        store[name] = value

    def fake_get(name: str):
        return store.get(name)

    def fake_delete(name: str) -> None:
        store.pop(name, None)

    # Patch at the server.py import site — that's where the CRUD
    # endpoints actually look them up.
    monkeypatch.setattr("server.set_secret", fake_set)
    monkeypatch.setattr("server.get_secret", fake_get)
    monkeypatch.setattr("server.delete_secret", fake_delete)
    return store


@pytest.fixture
def client(keyring_store):
    """Fresh TestClient against a temp SQLite DB. Keyring stubbed."""
    from fastapi.testclient import TestClient
    import server as srv

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp) / ".dialekt"
        tmp_dir.mkdir(parents=True)

        original_db = srv.DB_PATH
        original_cfg = srv.SETTINGS_FILE
        original_ddir = srv.DIALEKT_DIR

        srv.DB_PATH = tmp_dir / "dialekt.db"
        srv.SETTINGS_FILE = tmp_dir / "config.json"
        srv.DIALEKT_DIR = tmp_dir

        with TestClient(srv.app, raise_server_exceptions=True) as c:
            yield c

        srv.DB_PATH = original_db
        srv.SETTINGS_FILE = original_cfg
        srv.DIALEKT_DIR = original_ddir


# ── Happy-path create ───────────────────────────────────────────────────────


def test_create_stdio_with_env_secrets(client, keyring_store):
    r = client.post("/mcp-servers", json={
        "name": "github",
        "transport": "stdio",
        "command": ["npx", "-y", "@modelcontextprotocol/server-github"],
        "env_refs": {"GITHUB_TOKEN": "github_token"},
        "env_secrets": [{"ref": "github_token", "value": "ghp_TESTVALUE123"}],
    })
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["name"] == "github"
    assert body["transport"] == "stdio"
    assert body["command"] == ["npx", "-y", "@modelcontextprotocol/server-github"]
    assert body["env_refs"] == {"GITHUB_TOKEN": "github_token"}
    # Secret written under mcp.<server>.<ref>
    assert keyring_store["mcp.github.github_token"] == "ghp_TESTVALUE123"
    # Secret must NEVER appear in the response JSON.
    assert "ghp_TESTVALUE123" not in r.text
    assert "env_secrets" not in body


def test_create_http_with_bearer(client, keyring_store):
    r = client.post("/mcp-servers", json={
        "name": "jira",
        "transport": "http",
        "url": "https://jira.example/mcp",
        "auth_type": "bearer",
        "auth_token": "bearer_TOKEN_ABC",
    })
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["auth_type"] == "bearer"
    assert body["has_auth_token"] is True
    # Token written under default ref "auth_token"
    assert keyring_store["mcp.jira.auth_token"] == "bearer_TOKEN_ABC"
    assert "bearer_TOKEN_ABC" not in r.text


# ── Validation ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize("bad_name", ["GitHub", "github_2", "1github", "", "x" * 70])
def test_create_rejects_bad_name_pattern(client, bad_name):
    r = client.post("/mcp-servers", json={
        "name": bad_name,
        "transport": "stdio",
        "command": ["echo", "ok"],
    })
    assert r.status_code == 422


def test_create_stdio_requires_command(client):
    r = client.post("/mcp-servers", json={
        "name": "no-cmd",
        "transport": "stdio",
    })
    assert r.status_code == 422
    assert "command" in r.text


def test_create_http_requires_url(client):
    r = client.post("/mcp-servers", json={
        "name": "no-url",
        "transport": "http",
    })
    assert r.status_code == 422
    assert "url" in r.text


def test_create_rejects_duplicate_name(client, keyring_store):
    assert client.post("/mcp-servers", json={
        "name": "dup",
        "transport": "stdio",
        "command": ["echo"],
    }).status_code == 201
    r = client.post("/mcp-servers", json={
        "name": "dup",
        "transport": "stdio",
        "command": ["echo"],
    })
    assert r.status_code == 409


# ── Read ────────────────────────────────────────────────────────────────────


def test_list_and_get_single(client, keyring_store):
    client.post("/mcp-servers", json={
        "name": "alpha",
        "transport": "stdio",
        "command": ["echo"],
    })
    created = client.post("/mcp-servers", json={
        "name": "beta",
        "transport": "stdio",
        "command": ["echo"],
    }).json()

    listing = client.get("/mcp-servers").json()
    names = {item["name"] for item in listing}
    assert names == {"alpha", "beta"}

    one = client.get(f"/mcp-servers/{created['id']}").json()
    assert one["name"] == "beta"


def test_get_unknown_returns_404(client):
    r = client.get("/mcp-servers/nonexistent")
    assert r.status_code == 404


# ── Update ──────────────────────────────────────────────────────────────────


def test_patch_partial_update_preserves_other_fields(client, keyring_store):
    created = client.post("/mcp-servers", json={
        "name": "patchme",
        "transport": "stdio",
        "command": ["echo", "old"],
        "timeout_seconds": 30.0,
    }).json()

    r = client.patch(f"/mcp-servers/{created['id']}", json={
        "timeout_seconds": 60.0,
    })
    assert r.status_code == 200, r.text
    updated = r.json()
    assert updated["timeout_seconds"] == 60.0
    assert updated["command"] == ["echo", "old"]   # untouched
    assert updated["name"] == "patchme"            # untouched


def test_patch_rename_migrates_keyring(client, keyring_store):
    """Rename must move every secret under the new server name
    atomically — read-all → write-all-new → delete-all-old.
    """
    created = client.post("/mcp-servers", json={
        "name": "oldname",
        "transport": "stdio",
        "command": ["echo"],
        "env_refs": {"TOK": "tok"},
        "env_secrets": [{"ref": "tok", "value": "SECRET_V"}],
    }).json()
    assert keyring_store.get("mcp.oldname.tok") == "SECRET_V"

    r = client.patch(f"/mcp-servers/{created['id']}", json={"name": "newname"})
    assert r.status_code == 200, r.text
    # Old key gone, new key holds the secret.
    assert keyring_store.get("mcp.oldname.tok") is None
    assert keyring_store.get("mcp.newname.tok") == "SECRET_V"


def test_patch_rename_rejects_duplicate(client, keyring_store):
    client.post("/mcp-servers", json={
        "name": "takenalready",
        "transport": "stdio",
        "command": ["echo"],
    })
    created = client.post("/mcp-servers", json={
        "name": "mine",
        "transport": "stdio",
        "command": ["echo"],
    }).json()
    r = client.patch(f"/mcp-servers/{created['id']}", json={"name": "takenalready"})
    assert r.status_code == 409


# ── Delete ──────────────────────────────────────────────────────────────────


def test_delete_removes_row_and_keyring(client, keyring_store):
    created = client.post("/mcp-servers", json={
        "name": "ephemeral",
        "transport": "stdio",
        "command": ["echo"],
        "env_refs": {"A": "a", "B": "b"},
        "env_secrets": [
            {"ref": "a", "value": "VA"},
            {"ref": "b", "value": "VB"},
        ],
    }).json()
    assert keyring_store["mcp.ephemeral.a"] == "VA"
    assert keyring_store["mcp.ephemeral.b"] == "VB"

    r = client.delete(f"/mcp-servers/{created['id']}")
    assert r.status_code == 204

    assert client.get(f"/mcp-servers/{created['id']}").status_code == 404
    assert keyring_store.get("mcp.ephemeral.a") is None
    assert keyring_store.get("mcp.ephemeral.b") is None


def test_delete_unknown_returns_404(client):
    assert client.delete("/mcp-servers/nope").status_code == 404


# ── Secrets-never-leaked regression ─────────────────────────────────────────


def test_response_never_leaks_secret_value(client, keyring_store):
    secret = "DONOTLEAK_0xDEADBEEF"
    created = client.post("/mcp-servers", json={
        "name": "privacy",
        "transport": "stdio",
        "command": ["echo"],
        "env_refs": {"TOK": "tok"},
        "env_secrets": [{"ref": "tok", "value": secret}],
    })
    assert secret not in created.text
    assert secret not in client.get("/mcp-servers").text
    assert secret not in client.get(f"/mcp-servers/{created.json()['id']}").text


# ── Test endpoint (external MCP) ────────────────────────────────────────────


def test_test_endpoint_unreachable_returns_success_false(client, keyring_store):
    created = client.post("/mcp-servers", json={
        "name": "unreachable",
        "transport": "stdio",
        "command": ["/bin/definitely-not-a-real-binary-xyz"],
        "timeout_seconds": 5.0,
    }).json()
    r = client.post(f"/mcp-servers/{created['id']}/test")
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is False
    assert body["error"]
    # Last-test columns updated accordingly.
    one = client.get(f"/mcp-servers/{created['id']}").json()
    assert one["last_test_ok"] is False
    assert one["last_test_error"]
    assert one["last_test_at"]


def test_test_endpoint_missing_secret_fails_cleanly(client, keyring_store):
    """If manifest references a secret that isn't in the keyring, the test
    endpoint must surface a readable error — not 500.
    """
    created = client.post("/mcp-servers", json={
        "name": "missingsecret",
        "transport": "stdio",
        "command": ["echo", "hi"],
        "env_refs": {"TOK": "tok"},
        # No env_secrets — so mcp.missingsecret.tok is NOT in keyring.
    }).json()
    r = client.post(f"/mcp-servers/{created['id']}/test")
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is False
    assert "secrets.tok" in body["error"] or "tok" in body["error"]
