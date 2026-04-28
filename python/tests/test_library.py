"""Tests for the public agent library endpoints (desktop side).

Cloud sync is mocked — the desktop tests assert that the local SQLite
cache + endpoints behave correctly. The cloud's GET /public/library is
covered separately in dialekt-cloud/tests/.
"""
from __future__ import annotations

import json
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


# Use the actual seeded translator manifest — proves the pipeline
# end-to-end including manifest validator round-trip.
def _make_sample():
    from dialekt_cloud.services.library_seed import LIBRARY_TEMPLATES
    for t in LIBRARY_TEMPLATES:
        if t.id == "translator-ru-en":
            return t.manifest_yaml
    raise RuntimeError("seed translator missing")


import sys
sys.path.insert(0, str(__import__("pathlib").Path(__file__).parents[2] / "dialekt-cloud" / "src"))
_SAMPLE_MANIFEST = _make_sample()


def _seed_one(client, *, slug="test-translator", category="documents",
              requires_connection=False, manifest=_SAMPLE_MANIFEST):
    """Insert a row directly into library_templates so we can exercise
    the read endpoints without needing a running cloud."""
    import asyncio
    import server as srv

    async def go():
        await srv.db.execute(
            """
            INSERT OR REPLACE INTO library_templates(
                id, manifest_yaml, name, description, category, tags,
                requires_connection, requires_mcp, version, signature, cached_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?, datetime('now'))
            """,
            (
                slug, manifest, "RU/EN Translator", "Translates text",
                category, json.dumps(["test", "translator"]),
                int(requires_connection), 0, "1.0.0", None,
            ),
        )
        await srv.db.commit()
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(go())
    finally:
        loop.close()


def test_list_library_empty(client):
    r = client.get("/library")
    assert r.status_code == 200
    body = r.json()
    assert body["entries"] == []


def test_list_library_returns_seeded_entries(client):
    _seed_one(client)
    r = client.get("/library")
    assert r.status_code == 200
    entries = r.json()["entries"]
    assert any(e["id"] == "test-translator" for e in entries)
    # manifest_yaml dropped from list response (cheap browsing).
    for e in entries:
        assert "manifest_yaml" not in e


def test_list_library_filter_by_category(client):
    _seed_one(client, slug="test-doc-summary", category="documents")
    _seed_one(client, slug="test-sql", category="data-analytics",
              requires_connection=True)
    r = client.get("/library", params={"category": "data-analytics"})
    ids = [e["id"] for e in r.json()["entries"]]
    assert "test-sql" in ids
    assert "test-doc-summary" not in ids


def test_list_library_filter_by_requires_connection(client):
    r = client.get("/library", params={"requires_connection": True})
    assert all(e["requires_connection"] for e in r.json()["entries"])
    r = client.get("/library", params={"requires_connection": False})
    assert all(not e["requires_connection"] for e in r.json()["entries"])


def test_list_library_search_substring(client):
    r = client.get("/library", params={"search": "translator"})
    ids = [e["id"] for e in r.json()["entries"]]
    assert "test-translator" in ids


def test_get_library_template_returns_manifest(client):
    _seed_one(client)
    r = client.get("/library/test-translator")
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == "test-translator"
    assert "manifest_yaml" in body
    assert "RU/EN Translator" in body["manifest_yaml"]
    # Wizard "Customize" needs requires_secrets to render badges and
    # prompt the user to fill them.
    assert "requires_secrets" in body
    assert isinstance(body["requires_secrets"], list)


def test_get_library_template_404(client):
    r = client.get("/library/does-not-exist")
    assert r.status_code == 404


def test_library_list_includes_requires_secrets(client):
    """Catalog response carries requires_secrets so the LibraryScreen
    can render badges without fetching each manifest individually."""
    secret_yaml = """\
metadata:
  name: "Needs creds"
secrets_required:
  - name: "bitrix_webhook_url"
    description: "IBA Bitrix webhook"
    required: true
  - name: "instagram_access_token"
    description: "IG long-lived token"
output:
  format: "markdown"
"""
    _seed_one(client, slug="creds-agent", manifest=secret_yaml)
    r = client.get("/library")
    entries = {e["id"]: e for e in r.json()["entries"]}
    assert "creds-agent" in entries
    assert entries["creds-agent"]["requires_secrets"] == [
        "bitrix_webhook_url",
        "instagram_access_token",
    ]


def test_library_get_tolerates_malformed_manifest(client):
    """A library row with a broken manifest still returns 200 — just
    with empty requires_secrets — rather than 500ing the whole
    Library screen."""
    _seed_one(client, slug="broken-manifest", manifest="not: valid: yaml: !!!")
    r = client.get("/library/broken-manifest")
    # Some YAML strings parse to None / non-dict; either way we tolerate.
    assert r.status_code == 200
    assert r.json()["requires_secrets"] == []


def test_install_library_template_creates_agent_with_source_link(client):
    # Install — should succeed and link source_template_id
    r = client.post("/library/test-translator/install")
    assert r.status_code == 201, r.text
    body = r.json()
    assert "id" in body
    assert body["name"] == "RU/EN Translator"
    agent_id = body["id"]

    # Read the agent back and verify source_template_id is set
    import asyncio
    import server as srv

    async def fetch():
        cur = await srv.db.execute(
            "SELECT source_template_id FROM agents WHERE id = ?", (agent_id,)
        )
        return await cur.fetchone()
    loop = asyncio.new_event_loop()
    try:
        row = loop.run_until_complete(fetch())
    finally:
        loop.close()
    assert row[0] == "test-translator"


def test_install_unknown_template_returns_404(client):
    r = client.post("/library/no-such-template/install")
    assert r.status_code == 404
