"""
Integration tests for ClickHouse MCP server.

Prerequisites (run from tests/integration/):
    docker compose up -d --wait
    cd ../.. && source venv/bin/activate
    python -m pytest tests/integration/test_clickhouse_integration.py -v

Skipped automatically when DIALEKT_INTEGRATION_CLICKHOUSE env var is not set
or the DB is unreachable.
"""
import os
import tempfile
from pathlib import Path

import pytest

CH_URL = os.environ.get(
    "DIALEKT_INTEGRATION_CLICKHOUSE",
    "http://dialekt_test:dialekt_test@localhost:18123",
)
CH_DB = "dialekt_integration"


def _can_connect() -> bool:
    try:
        import httpx
        r = httpx.get(f"{CH_URL}/ping", timeout=3)
        return r.status_code == 200
    except Exception:
        return False


@pytest.fixture(scope="module")
def client():
    if not _can_connect():
        pytest.skip("ClickHouse not reachable")

    from fastapi.testclient import TestClient
    import server as srv

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp) / ".dialekt"
        tmp_dir.mkdir(parents=True)
        srv.DB_PATH = tmp_dir / "dialekt.db"
        srv.SETTINGS_FILE = tmp_dir / "config.json"
        srv.DIALEKT_DIR = tmp_dir
        with TestClient(srv.app, raise_server_exceptions=True) as c:
            yield c
        srv.DB_PATH = srv.DIALEKT_DIR = srv.SETTINGS_FILE = None


@pytest.fixture(scope="module")
def conn_id(client):
    """Create a live ClickHouse connection and return its ID."""
    r = client.post("/clickhouse/connections", json={
        "name": "integration-clickhouse",
        "host": "localhost",
        "port": 18123,
        "database": CH_DB,
        "username": "dialekt_test",
        "password": "dialekt_test",
    })
    assert r.status_code == 201, r.text
    cid = r.json()["id"]
    yield cid
    client.delete(f"/clickhouse/connections/{cid}")


def test_connection_test_ok(client, conn_id):
    r = client.post(f"/clickhouse/connections/{conn_id}/test")
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_list_schemas(client, conn_id):
    r = client.get(f"/clickhouse/connections/{conn_id}/schemas")
    assert r.status_code == 200
    schema_names = [s["schema_name"] for s in r.json()]
    assert CH_DB in schema_names


def test_list_tables(client, conn_id):
    r = client.get(f"/clickhouse/connections/{conn_id}/schemas/{CH_DB}/tables")
    assert r.status_code == 200
    tables = [t["table_name"] for t in r.json()]
    assert "customers" in tables
    assert "orders" in tables
    assert "events" in tables


def test_describe_table(client, conn_id):
    r = client.get(
        f"/clickhouse/connections/{conn_id}/schemas/{CH_DB}/tables/customers/describe"
    )
    assert r.status_code == 200
    cols = {c["column_name"] for c in r.json()}
    assert "id" in cols
    assert "email" in cols
    assert "country" in cols


def test_sample_rows(client, conn_id):
    r = client.get(
        f"/clickhouse/connections/{conn_id}/schemas/{CH_DB}/tables/customers/sample",
        params={"limit": 3},
    )
    assert r.status_code == 200
    data = r.json()
    assert "columns" in data
    assert "rows" in data
    assert len(data["rows"]) <= 3


def test_execute_count_query(client, conn_id):
    r = client.post(
        f"/clickhouse/connections/{conn_id}/query",
        json={"sql": f"SELECT count() AS cnt FROM {CH_DB}.customers"},
    )
    assert r.status_code == 200
    data = r.json()
    assert "rows" in data
    assert int(data["rows"][0][0]) >= 500


def test_execute_aggregation_query(client, conn_id):
    sql = f"""
        SELECT country, count() AS customer_count
        FROM {CH_DB}.customers
        GROUP BY country
        ORDER BY customer_count DESC
        LIMIT 5
    """
    r = client.post(f"/clickhouse/connections/{conn_id}/query", json={"sql": sql})
    assert r.status_code == 200
    rows = r.json()["rows"]
    assert len(rows) > 0


def test_events_table_large_count(client, conn_id):
    r = client.post(
        f"/clickhouse/connections/{conn_id}/query",
        json={"sql": f"SELECT count() FROM {CH_DB}.events"},
    )
    assert r.status_code == 200
    cnt = int(r.json()["rows"][0][0])
    assert cnt >= 10000


def test_ddl_rejected(client, conn_id):
    r = client.post(
        f"/clickhouse/connections/{conn_id}/query",
        json={"sql": f"DROP TABLE {CH_DB}.customers"},
    )
    assert r.status_code == 400


def test_insert_rejected(client, conn_id):
    r = client.post(
        f"/clickhouse/connections/{conn_id}/query",
        json={
            "sql": f"INSERT INTO {CH_DB}.customers (id, email, full_name, country) VALUES (9999, 'x@y.com', 'X', 'US')"
        },
    )
    assert r.status_code == 400


def test_event_type_breakdown(client, conn_id):
    sql = f"""
        SELECT event_type, count() AS cnt
        FROM {CH_DB}.events
        GROUP BY event_type
        ORDER BY cnt DESC
    """
    r = client.post(f"/clickhouse/connections/{conn_id}/query", json={"sql": sql})
    assert r.status_code == 200
    rows = r.json()["rows"]
    assert len(rows) >= 2
    event_types = [row[0] for row in rows]
    assert "pageview" in event_types or "click" in event_types
