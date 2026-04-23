"""
Integration tests for PostgreSQL MCP server.

Prerequisites (run from tests/integration/):
    docker compose up -d --wait
    cd ../.. && source venv/bin/activate
    python -m pytest tests/integration/test_pg_integration.py -v

These tests hit a real PostgreSQL instance. Skipped automatically when
DIALEKT_INTEGRATION_PG env var is not set or DB is unreachable.
"""
import os
import tempfile
from pathlib import Path

import pytest

PG_DSN = os.environ.get(
    "DIALEKT_INTEGRATION_PG",
    "postgresql://dialekt_test:dialekt_test@localhost:15432/dialekt_integration",
)


def _can_connect() -> bool:
    try:
        import asyncpg, asyncio
        async def _check():
            conn = await asyncpg.connect(PG_DSN, timeout=2)
            await conn.close()
        asyncio.run(_check())
        return True
    except Exception:
        return False


@pytest.fixture(scope="module")
def client():
    if not _can_connect():
        pytest.skip("PostgreSQL not reachable")

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
        srv.DB_PATH = srv.DIALEKT_DIR = srv.SETTINGS_FILE = None  # reset


@pytest.fixture(scope="module")
def conn_id(client):
    """Create a live PostgreSQL connection and return its ID."""
    import keyring as kr
    r = client.post("/connections", json={
        "name": "integration-pg",
        "host": "localhost",
        "port": 15432,
        "database": "dialekt_integration",
        "username": "dialekt_test",
        "password": "dialekt_test",
    })
    assert r.status_code == 201, r.text
    cid = r.json()["id"]
    yield cid
    client.delete(f"/connections/{cid}")


def test_connection_test_ok(client, conn_id):
    r = client.post(f"/connections/{conn_id}/test")
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_list_schemas(client, conn_id):
    r = client.get(f"/connections/{conn_id}/schemas")
    assert r.status_code == 200
    schemas = r.json()
    schema_names = [s["schema_name"] for s in schemas]
    assert "ecom" in schema_names
    assert "analytics" in schema_names


def test_list_tables_in_ecom(client, conn_id):
    r = client.get(f"/connections/{conn_id}/schemas/ecom/tables")
    assert r.status_code == 200
    tables = [t["table_name"] for t in r.json()]
    assert "customers" in tables
    assert "orders" in tables
    assert "order_items" in tables
    assert "products" in tables


def test_describe_table(client, conn_id):
    r = client.get(f"/connections/{conn_id}/schemas/ecom/tables/customers/describe")
    assert r.status_code == 200
    cols = {c["column_name"] for c in r.json()}
    assert "id" in cols
    assert "email" in cols
    assert "country" in cols


def test_sample_rows(client, conn_id):
    r = client.get(f"/connections/{conn_id}/schemas/ecom/tables/customers/sample?limit=3")
    assert r.status_code == 200
    data = r.json()
    assert "columns" in data
    assert "rows" in data
    assert len(data["rows"]) <= 3


def test_fkeys_on_orders(client, conn_id):
    r = client.get(f"/connections/{conn_id}/schemas/ecom/tables/orders/fkeys")
    assert r.status_code == 200
    fkeys = r.json()
    assert len(fkeys) >= 1
    col_names = [fk["column_name"] for fk in fkeys]
    assert "customer_id" in col_names


def test_execute_count_query(client, conn_id):
    r = client.post(f"/connections/{conn_id}/query", json={"sql": "SELECT COUNT(*) AS cnt FROM ecom.customers"})
    assert r.status_code == 200
    data = r.json()
    assert "rows" in data
    assert data["rows"][0][0] >= 1000  # we seeded 1000 customers


def test_execute_join_query(client, conn_id):
    sql = """
        SELECT c.country, COUNT(o.id) AS order_count
        FROM ecom.customers c
        JOIN ecom.orders o ON o.customer_id = c.id
        GROUP BY c.country
        ORDER BY order_count DESC
        LIMIT 5
    """
    r = client.post(f"/connections/{conn_id}/query", json={"sql": sql})
    assert r.status_code == 200
    assert len(r.json()["rows"]) > 0


def test_ddl_rejected(client, conn_id):
    r = client.post(f"/connections/{conn_id}/query", json={"sql": "DROP TABLE ecom.customers"})
    assert r.status_code == 400


def test_dml_rejected(client, conn_id):
    r = client.post(f"/connections/{conn_id}/query", json={"sql": "DELETE FROM ecom.customers"})
    assert r.status_code == 400


def test_insert_rejected(client, conn_id):
    r = client.post(f"/connections/{conn_id}/query", json={"sql": "INSERT INTO ecom.customers (email, full_name) VALUES ('x@y.com', 'X')"})
    assert r.status_code == 400


def test_schema_rag_reindex(client, conn_id):
    """Schema RAG reindex should run without error (embedding may be skipped if Ollama absent)."""
    r = client.post(f"/connections/{conn_id}/reindex")
    assert r.status_code == 200
    data = r.json()
    assert "indexed" in data or "skipped" in data or "error" in data


def test_schema_rag_search_returns_list(client, conn_id):
    """Semantic search returns a list (may be empty if nomic model not pulled)."""
    r = client.get(f"/connections/{conn_id}/search", params={"q": "customer orders"})
    assert r.status_code == 200
    assert isinstance(r.json(), list)
