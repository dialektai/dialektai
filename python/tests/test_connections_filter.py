"""Regression: each /{driver}-connections list endpoint must return
ONLY rows of its own type.

Before 2026-04-24 all three list endpoints did a bare
`SELECT * FROM connections` with no WHERE clause, so rows of every type
came back from every endpoint. The Settings → Connections UI fetched
all three endpoints and tagged each row with a `_driver` based on which
endpoint returned it — which meant every connection showed up three
times. See docs/OVERNIGHT_E2E_REPORT_2026-04-23.md §N2.
"""
import tempfile
import uuid
from pathlib import Path

import pytest


@pytest.fixture(scope="module")
def client():
    """Spin up a TestClient against a temp DB so we can seed rows
    without touching the user's live ~/.dialekt/dialekt.db.
    """
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


def _seed(client, driver: str, name: str) -> str:
    """Create a connection via the driver's POST endpoint, return its id."""
    prefix = {
        "postgres": "/connections",
        "mysql": "/mysql-connections",
        "clickhouse": "/ch-connections",
    }[driver]
    body = {
        "name": name,
        "host": "localhost",
        "database": "db",
        "username": "u",
    }
    # pg and mysql endpoints require a password; clickhouse doesn't.
    if driver in ("postgres", "mysql"):
        body["password"] = "p"
    r = client.post(prefix, json=body)
    assert r.status_code == 201, f"seed {driver} {name} failed: {r.status_code} {r.text}"
    return r.json()["id"]


def test_pg_endpoint_returns_only_postgres(client):
    pg_id = _seed(client, "postgres", f"pg-{uuid.uuid4().hex[:8]}")
    mysql_id = _seed(client, "mysql", f"mysql-{uuid.uuid4().hex[:8]}")
    ch_id = _seed(client, "clickhouse", f"ch-{uuid.uuid4().hex[:8]}")

    rows = client.get("/connections").json()
    ids = {r["id"] for r in rows}
    types = {r["type"] for r in rows}

    assert pg_id in ids, "expected the pg row"
    assert mysql_id not in ids, "mysql row should not appear on /connections"
    assert ch_id not in ids, "clickhouse row should not appear on /connections"
    # Type column must be strictly postgres flavor — no cross-type leakage.
    assert types <= {"postgresql", "postgres"}, f"unexpected types on /connections: {types}"

    # Cleanup so the next test starts fresh.
    client.delete(f"/connections/{pg_id}")
    client.delete(f"/mysql-connections/{mysql_id}")
    client.delete(f"/ch-connections/{ch_id}")


def test_mysql_endpoint_returns_only_mysql(client):
    pg_id = _seed(client, "postgres", f"pg-{uuid.uuid4().hex[:8]}")
    mysql_id = _seed(client, "mysql", f"mysql-{uuid.uuid4().hex[:8]}")
    ch_id = _seed(client, "clickhouse", f"ch-{uuid.uuid4().hex[:8]}")

    rows = client.get("/mysql-connections").json()
    ids = {r["id"] for r in rows}
    types = {r["type"] for r in rows}

    assert mysql_id in ids
    assert pg_id not in ids
    assert ch_id not in ids
    assert types == {"mysql"}, f"unexpected types on /mysql-connections: {types}"

    client.delete(f"/connections/{pg_id}")
    client.delete(f"/mysql-connections/{mysql_id}")
    client.delete(f"/ch-connections/{ch_id}")


def test_ch_endpoint_returns_only_clickhouse(client):
    pg_id = _seed(client, "postgres", f"pg-{uuid.uuid4().hex[:8]}")
    mysql_id = _seed(client, "mysql", f"mysql-{uuid.uuid4().hex[:8]}")
    ch_id = _seed(client, "clickhouse", f"ch-{uuid.uuid4().hex[:8]}")

    rows = client.get("/ch-connections").json()
    ids = {r["id"] for r in rows}
    types = {r["type"] for r in rows}

    assert ch_id in ids
    assert pg_id not in ids
    assert mysql_id not in ids
    assert types == {"clickhouse"}, f"unexpected types on /ch-connections: {types}"

    client.delete(f"/connections/{pg_id}")
    client.delete(f"/mysql-connections/{mysql_id}")
    client.delete(f"/ch-connections/{ch_id}")


def test_ui_merge_produces_no_duplicates(client):
    """Simulate what the Settings → Connections UI does: fetch all three
    endpoints, concatenate, tag by origin endpoint. With the filter in
    place, each connection id must appear exactly once in the merged
    list (not three times as before the fix).
    """
    pg_id = _seed(client, "postgres", f"pg-{uuid.uuid4().hex[:8]}")
    mysql_id = _seed(client, "mysql", f"mysql-{uuid.uuid4().hex[:8]}")
    ch_id = _seed(client, "clickhouse", f"ch-{uuid.uuid4().hex[:8]}")

    merged = []
    for prefix, driver in [
        ("/connections", "postgres"),
        ("/mysql-connections", "mysql"),
        ("/ch-connections", "clickhouse"),
    ]:
        for row in client.get(prefix).json():
            merged.append({**row, "_driver": driver})

    # Every seeded id appears exactly once in the merged list.
    from collections import Counter
    id_counts = Counter(r["id"] for r in merged)
    assert id_counts[pg_id] == 1, f"pg row appeared {id_counts[pg_id]} times"
    assert id_counts[mysql_id] == 1, f"mysql row appeared {id_counts[mysql_id]} times"
    assert id_counts[ch_id] == 1, f"ch row appeared {id_counts[ch_id]} times"

    # And the driver tag matches what's in the row's type field.
    for row in merged:
        if row["id"] == pg_id:
            assert row["_driver"] == "postgres"
        elif row["id"] == mysql_id:
            assert row["_driver"] == "mysql"
        elif row["id"] == ch_id:
            assert row["_driver"] == "clickhouse"

    client.delete(f"/connections/{pg_id}")
    client.delete(f"/mysql-connections/{mysql_id}")
    client.delete(f"/ch-connections/{ch_id}")
