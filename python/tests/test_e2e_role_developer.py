"""Role 2 (Agent Developer) — end-to-end flows for building agents
through the desktop app's Settings + Builder Wizard surface.

Scope per docs/MULTI_ROLE_TEST_PLAN.md §2:
  Connection CRUD (3): add PG / MySQL / CH connections + per-driver /test
  Agent creation (5): publish varied manifests (SQL/pure LLM/code/Python),
                      bind where applicable, verify manifest round-trip
  Agent lifecycle (3): list, PATCH system_prompt, DELETE + binding CASCADE
  Settings pages (5): schema reload, bad-credential /test (negative),
                      schema-RAG reindex, /settings blob round-trip,
                      DELETE /sessions wipe

Chat-level tool exercise (e.g. "agent actually runs SELECT when asked")
is covered by test_e2e_role_user.py; this file stays at the REST /
import-yaml level to keep the developer suite fast and deterministic.

Runs with DIALEKT_RUN_E2E=1. Skips when the integration compose stack
isn't reachable. Never pollutes ~/.dialekt — uses a temp-dir override
of server.DB_PATH/SETTINGS_FILE/DIALEKT_DIR.
"""
from __future__ import annotations

import os
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest


# ── Gating ──────────────────────────────────────────────────────────────────

pytestmark = pytest.mark.skipif(
    os.environ.get("DIALEKT_RUN_E2E") != "1",
    reason="Role-E2E tests require live integration DBs — set DIALEKT_RUN_E2E=1",
)

# Integration compose endpoints (same as tests/integration/)
PG = dict(host="localhost", port=15432, database="dialekt_integration",
          username="dialekt_test", password="dialekt_test")
MYSQL = dict(host="localhost", port=13306, database="dialekt_integration",
             username="dialekt_test", password="dialekt_test")
CH = dict(host="localhost", port=18123, database="dialekt_integration",
          username="dialekt_test", password="dialekt_test")


# ── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def client():
    """TestClient against server.py, temp-DB override."""
    from fastapi.testclient import TestClient
    import server as srv

    # GitHub runners + any headless box need the file keyring backend so
    # POST /connections can persist the password. Local dev usually has
    # the SecretService daemon, so we only set the backend when nothing
    # else is already selected.
    os.environ.setdefault("PYTHON_KEYRING_BACKEND", "keyrings.alt.file.PlaintextKeyring")

    with tempfile.TemporaryDirectory(prefix="dialekt-role-dev-") as tmp:
        tmp_dir = Path(tmp) / ".dialekt"
        tmp_dir.mkdir(parents=True)
        srv.DB_PATH = tmp_dir / "dialekt.db"
        srv.SETTINGS_FILE = tmp_dir / "config.json"
        srv.DIALEKT_DIR = tmp_dir
        with TestClient(srv.app, raise_server_exceptions=False) as c:
            yield c


# ── Manifest builder ────────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")


def _manifest(
    *,
    name: str,
    system_prompt: str = "you are a role-developer test agent",
    capabilities: list[str] | None = None,
    connection_types: list[str] | None = None,
    autonomy: str = "ask-before-write",
    variables: dict[str, str] | None = None,
) -> str:
    caps_block = "[]"
    if capabilities:
        caps_block = "\n" + "\n".join(f"    - {c}" for c in capabilities)

    conn_block = ""
    if connection_types:
        rows = "".join(
            f'    - type: "{t}"\n'
            '      role: "readonly"\n'
            f'      purpose: "role-developer E2E ({t})"\n'
            for t in connection_types
        )
        conn_block = "\nconnections:\n  required:\n" + rows + "\n"

    vars_block = ""
    if variables:
        rows = "".join(
            f'  {k}:\n'
            f'    type: "{typ}"\n'
            '    required: false\n'
            f'    description: "role-developer E2E var {k}"\n'
            for k, typ in variables.items()
        )
        vars_block = "\nvariables:\n" + rows + "\n"

    agent_uuid = str(uuid.uuid4())
    now = _now_iso()
    return (
        'spec_version: "1.0.1"\n'
        'minimum_dialekt_version: "1.0.0"\n\n'
        'metadata:\n'
        f'  id: "{agent_uuid}"\n'
        f'  name: "{name}"\n'
        f'  description: "role-developer E2E agent"\n'
        '  version: "1.0.0"\n'
        '  language: "en"\n'
        '  tags: []\n'
        '  author:\n'
        '    name: "t"\n'
        '    email: "t@t.t"\n'
        f'  created_at: "{now}"\n'
        f'  updated_at: "{now}"\n\n'
        'model:\n'
        '  preferred: "gemma2:2b"\n'
        '  acceptable: []\n'
        '  min_context_window: 32768\n'
        '  requirements:\n'
        '    min_ram_gb: 8\n'
        '    min_vram_gb: 0\n'
        '    recommended_ram_gb: 16\n'
        '  parameters:\n'
        '    temperature: 0.3\n'
        '    top_p: 0.95\n'
        '    max_tokens: 4096\n\n'
        f'system_prompt: |\n  {system_prompt}\n\n'
        f'capabilities:\n  groups: {caps_block}\n'
        + vars_block
        + conn_block
        + '\nautonomy:\n'
        f'  recommended: "{autonomy}"\n'
        f'  max_allowed: "{autonomy}"\n\n'
        'input:\n  type: "chat"\n  placeholder: "Ask me anything..."\n\n'
        'output:\n  format: "markdown"\n  streaming: true\n'
        '  destination:\n    type: "notification"\n\n'
        'trigger:\n  type: "interactive"\n'
    )


def _create_conn(client, prefix: str, cfg: dict, name: str) -> str:
    """POST a connection, return its id. Cleans up in the test itself."""
    body = {"name": name, **cfg}
    r = client.post(prefix, json=body)
    assert r.status_code == 201, f"{prefix} create failed: {r.status_code} {r.text}"
    return r.json()["id"]


# ── Connection management (3) ───────────────────────────────────────────────

def test_01_add_postgres_connection_and_test(client):
    cid = _create_conn(client, "/connections", PG, f"dev-pg-{uuid.uuid4().hex[:6]}")
    try:
        r = client.post(f"/connections/{cid}/test")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("ok") is True, body
        assert "version" in body
    finally:
        client.delete(f"/connections/{cid}")


def test_02_add_mysql_connection_and_test(client):
    cid = _create_conn(client, "/mysql-connections", MYSQL,
                       f"dev-mysql-{uuid.uuid4().hex[:6]}")
    try:
        r = client.post(f"/mysql-connections/{cid}/test")
        assert r.status_code == 200, r.text
        assert r.json().get("ok") is True
    finally:
        client.delete(f"/mysql-connections/{cid}")


def test_03_add_clickhouse_connection_and_test(client):
    cid = _create_conn(client, "/ch-connections", CH,
                       f"dev-ch-{uuid.uuid4().hex[:6]}")
    try:
        r = client.post(f"/ch-connections/{cid}/test")
        assert r.status_code == 200, r.text
        assert r.json().get("ok") is True
    finally:
        client.delete(f"/ch-connections/{cid}")


# ── Agent creation (5) ──────────────────────────────────────────────────────

def _publish(client, yaml_str: str) -> str:
    r = client.post("/agents/import-yaml", json={"manifest_yaml": yaml_str})
    assert r.status_code == 201, f"publish failed: {r.status_code} {r.text}"
    return r.json()["id"]


def test_04_sql_analyst_pg_publish_and_bind(client):
    conn_id = _create_conn(client, "/connections", PG,
                           f"sqlanalyst-pg-{uuid.uuid4().hex[:6]}")
    agent_id = None
    try:
        y = _manifest(
            name="SQL Analyst PG",
            system_prompt="SQL analyst with PostgreSQL access",
            capabilities=["database_read"],
            connection_types=["postgres"],
        )
        agent_id = _publish(client, y)

        b = client.post(
            f"/agents/{agent_id}/binding",
            json={"connection_id": conn_id, "connection_type": "postgres"},
        )
        assert b.status_code == 200, b.text

        g = client.get(f"/agents/{agent_id}/binding")
        assert g.status_code == 200
        assert g.json()["connection_id"] == conn_id
        assert g.json()["connection_type"] == "postgres"
    finally:
        if agent_id:
            client.delete(f"/agents/{agent_id}")
        client.delete(f"/connections/{conn_id}")


def test_05_pure_llm_agent_publishes_without_caps(client):
    agent_id = None
    try:
        y = _manifest(name="Pure LLM", autonomy="manual")
        agent_id = _publish(client, y)

        # GET round-trip — manifest YAML comes back intact.
        r = client.get(f"/agents/{agent_id}")
        assert r.status_code == 200
        assert "Pure LLM" in r.json().get("manifest_yaml", "")

        # No binding expected — confirm empty/null response.
        b = client.get(f"/agents/{agent_id}/binding")
        assert b.status_code == 200
        assert b.json().get("connection_id") in (None, "")
    finally:
        if agent_id:
            client.delete(f"/agents/{agent_id}")


def test_06_sql_analyst_mysql_publish_and_bind(client):
    conn_id = _create_conn(client, "/mysql-connections", MYSQL,
                           f"sqlanalyst-mysql-{uuid.uuid4().hex[:6]}")
    agent_id = None
    try:
        y = _manifest(
            name="SQL Analyst MySQL",
            system_prompt="SQL analyst with MySQL access",
            capabilities=["database_read"],
            connection_types=["mysql"],
        )
        agent_id = _publish(client, y)

        b = client.post(
            f"/agents/{agent_id}/binding",
            json={"connection_id": conn_id, "connection_type": "mysql"},
        )
        assert b.status_code == 200, b.text
        assert client.get(f"/agents/{agent_id}/binding").json()["connection_id"] == conn_id
    finally:
        if agent_id:
            client.delete(f"/agents/{agent_id}")
        client.delete(f"/mysql-connections/{conn_id}")


def test_07_code_review_agent_fs_and_shell(client):
    """Code-review profile: filesystem_read + shell_execute. Shell
    scenarios are only exercised when DIALEKT_E2E_ALLOW_SHELL=1 —
    otherwise we still publish the agent but skip any actual shell
    exec verification (none is done at this layer anyway).
    """
    agent_id = None
    try:
        y = _manifest(
            name="Code Reviewer",
            system_prompt="review Python code for issues",
            capabilities=["filesystem_read", "shell_execute"],
        )
        agent_id = _publish(client, y)

        # Verify capabilities made it through the validator intact
        manifest = client.get(f"/agents/{agent_id}").json()["manifest_yaml"]
        assert "filesystem_read" in manifest
        assert "shell_execute" in manifest
    finally:
        if agent_id:
            client.delete(f"/agents/{agent_id}")


def test_08_python_only_agent(client):
    agent_id = None
    try:
        # Dialekt's wizard maps "Python-only" to the `shell_execute`
        # capability since Open Interpreter runs Python via the shell
        # runtime; keep the same mapping here.
        y = _manifest(
            name="Python-Only",
            system_prompt="compute things with Python",
            capabilities=["shell_execute"],
        )
        agent_id = _publish(client, y)
        m = client.get(f"/agents/{agent_id}").json()["manifest_yaml"]
        assert "shell_execute" in m
    finally:
        if agent_id:
            client.delete(f"/agents/{agent_id}")


# ── Agent lifecycle (3) ─────────────────────────────────────────────────────

def test_09_list_agents_includes_newly_created(client):
    agent_id = _publish(client, _manifest(name=f"Listed-{uuid.uuid4().hex[:4]}"))
    try:
        r = client.get("/agents")
        assert r.status_code == 200
        ids = {a["id"] for a in r.json()}
        assert agent_id in ids
    finally:
        client.delete(f"/agents/{agent_id}")


def test_10_patch_agent_system_prompt_persists(client):
    agent_id = _publish(client, _manifest(name=f"Patched-{uuid.uuid4().hex[:4]}"))
    try:
        new_prompt = "updated system prompt 2026-04-24"
        r = client.patch(
            f"/agents/{agent_id}",
            json={"system_prompt": new_prompt},
        )
        assert r.status_code == 200, r.text

        g = client.get(f"/agents/{agent_id}")
        assert g.status_code == 200
        assert g.json()["system_prompt"] == new_prompt
    finally:
        client.delete(f"/agents/{agent_id}")


def test_11_delete_agent_cascades_binding(client):
    """Deleting an agent must also clear agent_bindings (FK CASCADE)."""
    conn_id = _create_conn(client, "/connections", PG,
                           f"cascade-{uuid.uuid4().hex[:6]}")
    agent_id = _publish(client, _manifest(
        name="CascadeTest",
        capabilities=["database_read"],
        connection_types=["postgres"],
    ))
    client.post(
        f"/agents/{agent_id}/binding",
        json={"connection_id": conn_id, "connection_type": "postgres"},
    )
    try:
        d = client.delete(f"/agents/{agent_id}")
        assert d.status_code == 200

        r = client.get(f"/agents/{agent_id}")
        assert r.status_code == 404

        # Direct SQLite check via server's DB path — binding row should
        # have been removed by ON DELETE CASCADE on agent_bindings.fkey.
        import sqlite3
        import server as srv
        with sqlite3.connect(srv.DB_PATH) as db:
            rows = db.execute(
                "SELECT agent_id FROM agent_bindings WHERE agent_id = ?",
                (agent_id,),
            ).fetchall()
            assert rows == [], f"orphan binding rows survived delete: {rows}"
    finally:
        client.delete(f"/connections/{conn_id}")


# ── Settings pages (5) ──────────────────────────────────────────────────────

def test_12_admin_reload_schema(client):
    r = client.post("/admin/reload-schema")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["errors"] == []
    assert "manual" in body["constants"]["autonomy_levels"]
    assert "package_version" in body


def test_13_connection_test_with_bad_password_fails_cleanly(client):
    """Negative: POST /{id}/test against a connection whose stored
    password is wrong must surface ok=false, NOT a 500.
    """
    cid = _create_conn(client, "/connections",
                       {**PG, "password": "this-is-wrong"},
                       f"badpass-{uuid.uuid4().hex[:6]}")
    try:
        r = client.post(f"/connections/{cid}/test")
        # Endpoint is expected to return 200 with {ok: false, error: ...}
        # (not a 500). A 503 is also acceptable (connection unavailable).
        assert r.status_code in (200, 503), r.text
        if r.status_code == 200:
            assert r.json().get("ok") is False
            assert r.json().get("error"), "error field must be populated"
    finally:
        client.delete(f"/connections/{cid}")


def test_14_schema_rag_reindex(client):
    cid = _create_conn(client, "/connections", PG,
                       f"reindex-{uuid.uuid4().hex[:6]}")
    try:
        r = client.post(f"/connections/{cid}/reindex")
        assert r.status_code == 200, r.text
        body = r.json()
        # Response shape is one of: {indexed: N} when embeddings model
        # is present, {skipped: true/reason} when nomic isn't pulled,
        # or {error: ...} on transient Ollama failure. All three are
        # valid — we just assert SOMETHING came back structured.
        assert any(k in body for k in ("indexed", "skipped", "error", "ok")), body
    finally:
        client.delete(f"/connections/{cid}")


def test_15_settings_blob_roundtrip(client):
    """Covers the 8 UI-only Settings pages (Personality, Appearance,
    Shortcuts, Permissions, Filesystem, Terminal, Performance,
    Privacy) in one shot — they all persist through POST /settings.
    """
    probe = f"role-dev-e2e-{uuid.uuid4().hex[:6]}"
    r_put = client.post("/settings", json={"ui_theme": "editorial-dark",
                                            "probe": probe})
    assert r_put.status_code == 200, r_put.text

    r_get = client.get("/settings")
    assert r_get.status_code == 200
    got = r_get.json()
    assert got.get("ui_theme") == "editorial-dark"
    assert got.get("probe") == probe


def test_16_delete_all_sessions_wipe(client):
    """Storage & Memory page: wipe button hits DELETE /sessions."""
    # Seed a session so wipe has something to remove. Sessions are
    # created implicitly on the first chat message; since we don't
    # want to spin up Ollama here, we'll create one directly via the
    # SQLite path (server exposes no explicit POST /sessions).
    import sqlite3
    import server as srv
    sid = f"seeded-{uuid.uuid4().hex[:8]}"
    with sqlite3.connect(srv.DB_PATH) as db:
        db.execute(
            "INSERT INTO sessions(id, title, updated_at) "
            "VALUES(?, 'probe', datetime('now'))",
            (sid,),
        )
        db.commit()

    before = client.get("/sessions").json()
    assert any(s["id"] == sid for s in before), "seed failed"

    r = client.delete("/sessions")
    assert r.status_code == 200, r.text

    after = client.get("/sessions").json()
    assert all(s["id"] != sid for s in after), "wipe did not remove seed"
