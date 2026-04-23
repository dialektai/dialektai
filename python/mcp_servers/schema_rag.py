"""
Schema RAG: semantic index of PostgreSQL table schemas.
Embeddings via nomic-embed-text:v1.5 (Ollama). Stored in schema_cache.db.
Gracefully skips when Ollama is unavailable.
"""
import json
import logging
import math
import sqlite3
import time
from pathlib import Path
from typing import Optional

import httpx

log = logging.getLogger("dialekt.schema_rag")

CACHE_DB = Path.home() / ".dialekt" / "schema_cache.db"
EMBED_MODEL = "nomic-embed-text:v1.5"
OLLAMA_URL = "http://localhost:11434"
TTL_SECONDS = 86400  # 24 h


async def check_model() -> bool:
    """Return True if EMBED_MODEL is available in Ollama. Logs a warning if not."""
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get(f"{OLLAMA_URL}/api/tags")
            r.raise_for_status()
            models = [m["name"] for m in r.json().get("models", [])]
            available = any(EMBED_MODEL in m or m.startswith(EMBED_MODEL.split(":")[0]) for m in models)
            if not available:
                log.warning(
                    f"Schema RAG: '{EMBED_MODEL}' not found in Ollama. "
                    f"Run: ollama pull {EMBED_MODEL}  — reindexing will skip until it's available."
                )
            return available
    except Exception:
        log.debug("Ollama not reachable — schema RAG embeddings will be skipped.")
        return False


async def pull_model() -> bool:
    """Pull EMBED_MODEL via Ollama API if not present. Returns True on success."""
    try:
        async with httpx.AsyncClient(timeout=300) as client:
            r = await client.post(f"{OLLAMA_URL}/api/pull", json={"name": EMBED_MODEL, "stream": False})
            r.raise_for_status()
            log.info(f"Schema RAG: pulled '{EMBED_MODEL}' successfully.")
            return True
    except Exception as e:
        log.warning(f"Schema RAG: failed to pull '{EMBED_MODEL}': {e}")
        return False


def _open() -> sqlite3.Connection:
    CACHE_DB.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(str(CACHE_DB))
    db.execute("""
        CREATE TABLE IF NOT EXISTS schema_entries (
            conn_id      TEXT NOT NULL,
            schema_name  TEXT NOT NULL,
            table_name   TEXT NOT NULL,
            description  TEXT NOT NULL,
            embedding    TEXT,           -- JSON float array
            indexed_at   INTEGER NOT NULL,
            PRIMARY KEY (conn_id, schema_name, table_name)
        )
    """)
    db.commit()
    return db


async def _embed(text: str) -> Optional[list[float]]:
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(
                f"{OLLAMA_URL}/api/embed",
                json={"model": EMBED_MODEL, "input": text},
            )
            r.raise_for_status()
            return r.json().get("embeddings", [None])[0]
    except Exception as e:
        log.debug(f"Embed skipped: {e}")
        return None


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    return dot / (na * nb) if na and nb else 0.0


async def reindex(conn_id: str, pool) -> dict:
    """Re-embed all tables in every schema for *conn_id*. Returns summary dict."""
    indexed = skipped = 0
    now = int(time.time())
    db = None
    try:
        db = _open()
        # fetch schemas
        async with pool.acquire() as c:
            schemas = [r["schema_name"] for r in await c.fetch(
                "SELECT schema_name FROM information_schema.schemata "
                "WHERE schema_name NOT IN ('pg_catalog','information_schema','pg_toast')"
            )]
        for schema in schemas:
            async with pool.acquire() as c:
                tables = [r["table_name"] for r in await c.fetch(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = $1 AND table_type = 'BASE TABLE'", schema,
                )]
            for table in tables:
                async with pool.acquire() as c:
                    cols = await c.fetch(
                        "SELECT column_name, data_type, is_nullable "
                        "FROM information_schema.columns "
                        "WHERE table_schema = $1 AND table_name = $2 "
                        "ORDER BY ordinal_position", schema, table,
                    )
                col_text = ", ".join(
                    f"{r['column_name']} {r['data_type']}{'?' if r['is_nullable'] == 'YES' else ''}"
                    for r in cols
                )
                desc = f"Table {schema}.{table}: {col_text}"
                vec = await _embed(desc)
                emb_json = json.dumps(vec) if vec is not None else None
                if vec is None:
                    skipped += 1
                else:
                    indexed += 1
                db.execute(
                    "INSERT OR REPLACE INTO schema_entries VALUES (?,?,?,?,?,?)",
                    (conn_id, schema, table, desc, emb_json, now),
                )
        db.commit()
        return {"indexed": indexed, "skipped": skipped}
    except Exception as e:
        log.warning(f"Reindex failed for {conn_id}: {e}")
        return {"indexed": indexed, "skipped": skipped, "error": str(e)}
    finally:
        if db:
            db.close()


async def search(conn_id: str, query: str, k: int = 5) -> list[dict]:
    """Semantic search over indexed tables. Returns [] when unavailable."""
    q_vec = await _embed(query)
    if q_vec is None:
        return []
    cutoff = int(time.time()) - TTL_SECONDS
    db = None
    try:
        db = _open()
        rows = db.execute(
            "SELECT schema_name, table_name, description, embedding "
            "FROM schema_entries WHERE conn_id = ? AND indexed_at > ? AND embedding IS NOT NULL",
            (conn_id, cutoff),
        ).fetchall()
    except Exception:
        return []
    finally:
        if db:
            db.close()

    scored = []
    for schema, table, desc, emb_json in rows:
        try:
            vec = json.loads(emb_json)
            scored.append((schema, table, desc, _cosine(q_vec, vec)))
        except Exception:
            continue

    scored.sort(key=lambda x: x[3], reverse=True)
    return [
        {"schema": s, "table": t, "description": d, "score": round(sc, 4)}
        for s, t, d, sc in scored[:k]
    ]


def clear(conn_id: str) -> None:
    try:
        db = _open()
        db.execute("DELETE FROM schema_entries WHERE conn_id = ?", (conn_id,))
        db.commit()
        db.close()
    except Exception as e:
        log.debug(f"Clear schema cache failed: {e}")
