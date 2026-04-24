"""
Integration tests for MySQL MCP server.

Prerequisites (run from tests/integration/):
    docker compose up -d --wait
    cd ../.. && source venv/bin/activate
    python -m pytest tests/integration/test_mysql_integration.py -v

Skipped automatically when DIALEKT_INTEGRATION_MYSQL env var is not set
or the DB is unreachable.
"""
import os
import tempfile
from pathlib import Path

import pytest

MYSQL_DSN = os.environ.get(
    "DIALEKT_INTEGRATION_MYSQL",
    "mysql://dialekt_test:dialekt_test@localhost:13306/dialekt_integration",
)


def _can_connect() -> bool:
    try:
        import aiomysql, asyncio
        async def _check():
            conn = await aiomysql.connect(
                host="localhost", port=13306,
                user="dialekt_test", password="dialekt_test",
                db="dialekt_integration", connect_timeout=2,
            )
            conn.close()
        asyncio.run(_check())
        return True
    except Exception:
        return False


@pytest.fixture(scope="module")
def client():
    if not _can_connect():
        pytest.skip("MySQL not reachable")

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
    """Create a live MySQL connection and return its ID."""
    r = client.post("/mysql-connections", json={
        "name": "integration-mysql",
        "host": "localhost",
        "port": 13306,
        "database": "dialekt_integration",
        "username": "dialekt_test",
        "password": "dialekt_test",
    })
    assert r.status_code == 201, r.text
    cid = r.json()["id"]
    yield cid
    client.delete(f"/mysql-connections/{cid}")


def test_connection_test_ok(client, conn_id):
    r = client.post(f"/mysql-connections/{conn_id}/test")
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_list_schemas(client, conn_id):
    r = client.get(f"/mysql-connections/{conn_id}/schemas")
    assert r.status_code == 200
    schema_names = r.json()  # list of bare strings
    assert "dialekt_integration" in schema_names


def test_list_tables(client, conn_id):
    r = client.get(f"/mysql-connections/{conn_id}/schemas/dialekt_integration/tables")
    assert r.status_code == 200
    tables = [t["name"] for t in r.json()]
    assert "customers" in tables
    assert "orders" in tables
    assert "products" in tables
    assert "order_items" in tables


def test_describe_table(client, conn_id):
    r = client.get(
        f"/mysql-connections/{conn_id}/schemas/dialekt_integration/tables/customers/describe"
    )
    assert r.status_code == 200
    cols = {c["column"] for c in r.json()}
    assert "id" in cols
    assert "email" in cols
    assert "country" in cols


def test_sample_rows(client, conn_id):
    r = client.get(
        f"/mysql-connections/{conn_id}/schemas/dialekt_integration/tables/customers/sample",
        params={"limit": 3},
    )
    assert r.status_code == 200
    data = r.json()
    assert "columns" in data
    assert "rows" in data
    assert len(data["rows"]) <= 3


def test_foreign_keys_on_orders(client, conn_id):
    r = client.get(
        f"/mysql-connections/{conn_id}/schemas/dialekt_integration/tables/orders/fkeys"
    )
    assert r.status_code == 200
    fkeys = r.json()
    assert len(fkeys) >= 1
    col_names = [fk["column"] for fk in fkeys]
    assert "customer_id" in col_names


def test_execute_count_query(client, conn_id):
    r = client.post(
        f"/mysql-connections/{conn_id}/query",
        json={"sql": "SELECT COUNT(*) AS cnt FROM customers"},
    )
    assert r.status_code == 200
    data = r.json()
    assert "rows" in data
    assert int(data["rows"][0][0]) >= 500


def test_execute_join_query(client, conn_id):
    sql = """
        SELECT c.country, COUNT(o.id) AS order_count
        FROM customers c
        JOIN orders o ON o.customer_id = c.id
        GROUP BY c.country
        ORDER BY order_count DESC
        LIMIT 5
    """
    r = client.post(f"/mysql-connections/{conn_id}/query", json={"sql": sql})
    assert r.status_code == 200
    assert len(r.json()["rows"]) > 0


def test_ddl_rejected(client, conn_id):
    # Server returns 422 (Unprocessable Entity) for SQL-safety rejections.
    r = client.post(
        f"/mysql-connections/{conn_id}/query",
        json={"sql": "DROP TABLE customers"},
    )
    assert r.status_code == 422


def test_dml_rejected(client, conn_id):
    r = client.post(
        f"/mysql-connections/{conn_id}/query",
        json={"sql": "DELETE FROM customers"},
    )
    assert r.status_code == 422


def test_insert_rejected(client, conn_id):
    r = client.post(
        f"/mysql-connections/{conn_id}/query",
        json={"sql": "INSERT INTO customers (email, full_name) VALUES ('x@y.com', 'X')"},
    )
    assert r.status_code == 422


def test_product_category_grouping(client, conn_id):
    sql = """
        SELECT category, COUNT(*) AS cnt, AVG(price_usd) AS avg_price
        FROM products
        GROUP BY category
        ORDER BY cnt DESC
    """
    r = client.post(f"/mysql-connections/{conn_id}/query", json={"sql": sql})
    assert r.status_code == 200
    rows = r.json()["rows"]
    assert len(rows) >= 2
    categories = [row[0] for row in rows]
    assert "Electronics" in categories
