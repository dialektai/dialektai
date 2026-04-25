"""
Endpoint tests for /llm/* and /ollama/install/* introduced in v0.21.

Uses the same TestClient fixture pattern as test_api_health.py — temp
DIALEKT_DIR so no real keychain or filesystem state is touched.
"""
import tempfile
from pathlib import Path

import pytest


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient
    import server as srv

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp) / ".dialekt"
        tmp_dir.mkdir(parents=True)

        original_db   = srv.DB_PATH
        original_cfg  = srv.SETTINGS_FILE
        original_ddir = srv.DIALEKT_DIR

        srv.DB_PATH       = tmp_dir / "dialekt.db"
        srv.SETTINGS_FILE = tmp_dir / "config.json"
        srv.DIALEKT_DIR   = tmp_dir

        with TestClient(srv.app, raise_server_exceptions=True) as c:
            yield c

        srv.DB_PATH       = original_db
        srv.SETTINGS_FILE = original_cfg
        srv.DIALEKT_DIR   = original_ddir


def test_llm_catalog_returns_ollama_and_providers(client):
    r = client.get("/llm/catalog")
    assert r.status_code == 200
    body = r.json()
    assert "ollama" in body and "providers" in body
    assert len(body["ollama"]) >= 30
    assert len(body["providers"]) >= 16
    # Spot-check a known provider
    ids = [p["id"] for p in body["providers"]]
    for must_have in ("anthropic", "openai", "gemini", "bedrock", "nvidia_nim", "groq"):
        assert must_have in ids, f"{must_have} missing from catalog"


def test_llm_catalog_under_regulated_mode_omits_providers(client):
    """Setting regulated_mode=True must hide cloud providers from /llm/catalog."""
    client.post("/settings", json={"regulated_mode": True})
    try:
        r = client.get("/llm/catalog")
        body = r.json()
        assert body.get("regulated_mode") is True
        assert body["providers"] == []
        # Ollama must still be available — local-first
        assert len(body["ollama"]) >= 30
    finally:
        client.post("/settings", json={"regulated_mode": False})


def test_llm_providers_lists_with_status(client):
    r = client.get("/llm/providers")
    assert r.status_code == 200
    body = r.json()
    assert "providers" in body
    assert len(body["providers"]) >= 16
    for p in body["providers"]:
        assert {"id", "name", "configured", "auth_kind"}.issubset(p.keys())


def test_llm_providers_under_regulated_mode_returns_empty(client):
    client.post("/settings", json={"regulated_mode": True})
    try:
        r = client.get("/llm/providers")
        body = r.json()
        assert body["regulated_mode"] is True
        assert body["providers"] == []
    finally:
        client.post("/settings", json={"regulated_mode": False})


def test_llm_save_credentials_unknown_provider_404(client):
    r = client.post("/llm/providers/nope_xyz/credentials", json={"api_key": "x"})
    assert r.status_code == 404


def test_llm_save_and_delete_credentials_roundtrip(client, monkeypatch):
    """Save then delete creds; secrets layer is mocked since we don't
    want to touch the real keychain in tests."""
    saved = {}

    def fake_set(name, value):
        saved[name] = value

    def fake_delete(name):
        saved.pop(name, None)

    monkeypatch.setattr("dialekt.secrets.set_secret", fake_set)
    monkeypatch.setattr("dialekt.secrets.delete_secret", fake_delete)

    r = client.post("/llm/providers/anthropic/credentials",
                    json={"api_key": "sk-test-fake-key"})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert "api_key" in body["saved_fields"]
    assert saved.get("provider_anthropic_api_key") == "sk-test-fake-key"

    r2 = client.delete("/llm/providers/anthropic/credentials")
    assert r2.status_code == 200
    assert r2.json()["ok"] is True
    assert "provider_anthropic_api_key" not in saved


def test_llm_current_returns_resolved_state(client):
    r = client.get("/llm/current")
    assert r.status_code == 200
    body = r.json()
    assert {"provider", "model", "litellm_model", "is_local", "configured"}.issubset(body.keys())
    # Default settings → ollama
    assert body["provider"] == "ollama"
    assert body["is_local"] is True
    assert body["litellm_model"].startswith("ollama_chat/")


def test_settings_roundtrip_preserves_model_provider(client):
    """The P0 bug guard: writing model_provider must persist, not get
    silently overwritten by default 'ollama'."""
    client.post("/settings", json={
        "model_provider": "anthropic",
        "model": "claude-opus-4-7",
    })
    try:
        s = client.get("/settings").json()
        assert s["model_provider"] == "anthropic"
        assert s["model"] == "claude-opus-4-7"

        r = client.get("/llm/current").json()
        assert r["provider"] == "anthropic"
        assert r["litellm_model"] == "anthropic/claude-opus-4-7"
        assert r["is_local"] is False
    finally:
        client.post("/settings", json={
            "model_provider": "ollama",
            "model": "gemma3:12b",
        })


def test_ollama_install_preview_shape(client, monkeypatch):
    """The preview endpoint should return supported=False on non-Linux,
    and a verifiable hash on Linux."""
    # Mock platform.system to test both paths
    import platform
    real_system = platform.system

    monkeypatch.setattr(platform, "system", lambda: "Darwin")
    r = client.get("/ollama/install/preview")
    body = r.json()
    assert body.get("supported") is False
    assert body.get("platform") == "darwin"

    monkeypatch.setattr(platform, "system", real_system)
