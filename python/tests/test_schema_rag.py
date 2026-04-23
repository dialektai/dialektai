"""
Schema RAG unit tests — no Ollama, no PostgreSQL needed.
Tests the cache DB, cosine similarity, and reindex/search with mocks.
"""
import json
import math
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))


# ── Helpers ───────────────────────────────────────────────────────────────────

def _unit(n: int) -> list[float]:
    """Unit vector of dimension n (all equal components, sum-of-squares = 1)."""
    v = [1.0 / math.sqrt(n)] * n
    return v


def _make_vec(dim_idx: int, n: int = 16) -> list[float]:
    """Canonical basis unit vector: 1.0 at position dim_idx, 0 elsewhere."""
    v = [0.0] * n
    v[dim_idx % n] = 1.0
    return v


# ── Cosine similarity (pure-Python, no DB) ─────────────────────────────────

def test_cosine_identical():
    from mcp_servers.schema_rag import _cosine
    v = _unit(8)
    assert abs(_cosine(v, v) - 1.0) < 1e-9


def test_cosine_orthogonal():
    from mcp_servers.schema_rag import _cosine
    a = [1.0, 0.0]
    b = [0.0, 1.0]
    assert abs(_cosine(a, b)) < 1e-9


def test_cosine_opposite():
    from mcp_servers.schema_rag import _cosine
    v = _unit(4)
    neg = [-x for x in v]
    assert abs(_cosine(v, neg) + 1.0) < 1e-9


# ── Cache DB open / write / read ──────────────────────────────────────────────

def test_open_creates_db(tmp_path):
    import mcp_servers.schema_rag as rag
    original = rag.CACHE_DB
    rag.CACHE_DB = tmp_path / "test_schema_cache.db"
    try:
        db = rag._open()
        db.close()
        assert (tmp_path / "test_schema_cache.db").exists()
    finally:
        rag.CACHE_DB = original


def test_open_idempotent(tmp_path):
    import mcp_servers.schema_rag as rag
    original = rag.CACHE_DB
    rag.CACHE_DB = tmp_path / "idem.db"
    try:
        db = rag._open(); db.close()
        db = rag._open(); db.close()
        # second open should not raise
    finally:
        rag.CACHE_DB = original


# ── search() with pre-seeded cache ────────────────────────────────────────────

@pytest.fixture
def rag_with_data(tmp_path):
    """Return schema_rag module with a pre-seeded cache."""
    import mcp_servers.schema_rag as rag
    import time
    original = rag.CACHE_DB
    rag.CACHE_DB = tmp_path / "rag.db"
    db = rag._open()
    now = int(time.time())
    entries = [
        ("conn-1", "public", "users",   "Table public.users: id int, name text?, email text?",  json.dumps(_make_vec(0))),
        ("conn-1", "public", "orders",  "Table public.orders: id int, user_id int, total float", json.dumps(_make_vec(1))),
        ("conn-1", "public", "products","Table public.products: id int, sku text, price float",  json.dumps(_make_vec(2))),
        ("conn-2", "public", "logs",    "Table public.logs: id int, message text?",              json.dumps(_make_vec(3))),
    ]
    for conn_id, schema, table, desc, emb in entries:
        db.execute(
            "INSERT OR REPLACE INTO schema_entries VALUES (?,?,?,?,?,?)",
            (conn_id, schema, table, desc, emb, now),
        )
    db.commit()
    db.close()
    yield rag
    rag.CACHE_DB = original


@pytest.mark.asyncio
async def test_search_returns_only_matching_conn(rag_with_data):
    rag = rag_with_data
    q_vec = _make_vec(0)  # identical to 'users' vec, orthogonal to conn-2 'logs'
    with patch.object(rag, "_embed", new=AsyncMock(return_value=q_vec)):
        results = await rag.search("conn-1", "user accounts", k=10)
    conn_ids_in_results = {r["schema"] + "." + r["table"] for r in results}
    assert "public.logs" not in conn_ids_in_results  # belongs to conn-2
    assert all("conn-2" not in r["description"] for r in results)


@pytest.mark.asyncio
async def test_search_ranking_order(rag_with_data):
    rag = rag_with_data
    q_vec = _make_vec(0)  # identical to users (dim 0), orthogonal to orders (dim 1) and products (dim 2)
    with patch.object(rag, "_embed", new=AsyncMock(return_value=q_vec)):
        results = await rag.search("conn-1", "something", k=3)
    assert len(results) == 3
    assert results[0]["table"] == "users"
    assert results[0]["score"] >= results[1]["score"] >= results[2]["score"]


@pytest.mark.asyncio
async def test_search_empty_when_embed_unavailable(rag_with_data):
    rag = rag_with_data
    with patch.object(rag, "_embed", new=AsyncMock(return_value=None)):
        results = await rag.search("conn-1", "anything", k=5)
    assert results == []


@pytest.mark.asyncio
async def test_search_respects_ttl(tmp_path):
    import mcp_servers.schema_rag as rag
    import time
    original = rag.CACHE_DB
    rag.CACHE_DB = tmp_path / "ttl.db"
    old_ts = int(time.time()) - rag.TTL_SECONDS - 1  # expired
    db = rag._open()
    db.execute(
        "INSERT OR REPLACE INTO schema_entries VALUES (?,?,?,?,?,?)",
        ("conn-x", "public", "stale", "Table public.stale: id int", json.dumps(_make_vec(0)), old_ts),
    )
    db.commit(); db.close()
    with patch.object(rag, "_embed", new=AsyncMock(return_value=_make_vec(0))):
        results = await rag.search("conn-x", "anything", k=5)
    assert results == []
    rag.CACHE_DB = original


# ── reindex() with mocked pool ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_reindex_stores_entries(tmp_path):
    import mcp_servers.schema_rag as rag
    original = rag.CACHE_DB
    rag.CACHE_DB = tmp_path / "ri.db"

    # mock pool
    async def mock_fetch(sql, *args):
        if "schemata" in sql:
            return [{"schema_name": "public"}]
        if "tables" in sql:
            return [{"table_name": "customers"}]
        if "columns" in sql:
            return [{"column_name": "id", "data_type": "integer", "is_nullable": "NO"},
                    {"column_name": "email", "data_type": "text", "is_nullable": "YES"}]
        return []

    mock_conn = AsyncMock()
    mock_conn.fetch = mock_fetch
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=_AsyncCtxMgr(mock_conn))

    vec = _make_vec(4)
    with patch.object(rag, "_embed", new=AsyncMock(return_value=vec)):
        result = await rag.reindex("conn-test", pool)

    assert result["indexed"] == 1
    assert result["skipped"] == 0

    db = rag._open()
    row = db.execute(
        "SELECT description, embedding FROM schema_entries WHERE conn_id = ?", ("conn-test",)
    ).fetchone()
    db.close()
    assert row is not None
    assert "customers" in row[0]
    assert json.loads(row[1]) == vec

    rag.CACHE_DB = original


@pytest.mark.asyncio
async def test_reindex_skips_when_embed_none(tmp_path):
    import mcp_servers.schema_rag as rag
    original = rag.CACHE_DB
    rag.CACHE_DB = tmp_path / "skip.db"

    async def mock_fetch(sql, *args):
        if "schemata" in sql:
            return [{"schema_name": "public"}]
        if "tables" in sql:
            return [{"table_name": "items"}]
        if "columns" in sql:
            return [{"column_name": "id", "data_type": "int", "is_nullable": "NO"}]
        return []

    mock_conn = AsyncMock()
    mock_conn.fetch = mock_fetch
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=_AsyncCtxMgr(mock_conn))

    with patch.object(rag, "_embed", new=AsyncMock(return_value=None)):
        result = await rag.reindex("conn-skip", pool)

    assert result["indexed"] == 0
    assert result["skipped"] == 1
    rag.CACHE_DB = original


# ── clear() ───────────────────────────────────────────────────────────────────

def test_clear_removes_entries(tmp_path):
    import mcp_servers.schema_rag as rag
    import time
    original = rag.CACHE_DB
    rag.CACHE_DB = tmp_path / "clear.db"
    db = rag._open()
    db.execute(
        "INSERT OR REPLACE INTO schema_entries VALUES (?,?,?,?,?,?)",
        ("conn-del", "public", "t", "desc", None, int(time.time())),
    )
    db.commit(); db.close()

    rag.clear("conn-del")

    db = rag._open()
    row = db.execute("SELECT 1 FROM schema_entries WHERE conn_id = 'conn-del'").fetchone()
    db.close()
    assert row is None
    rag.CACHE_DB = original


# ── Async context manager helper ─────────────────────────────────────────────

class _AsyncCtxMgr:
    def __init__(self, value):
        self._v = value
    def __call__(self, *a, **kw):
        return self
    async def __aenter__(self):
        return self._v
    async def __aexit__(self, *a):
        pass
