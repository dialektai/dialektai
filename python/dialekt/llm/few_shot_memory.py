"""
Goal 8.5 — Few-shot memory.

Stores successful user↔agent interactions with embeddings for semantic retrieval.
Uses nomic-embed-text (via Ollama). Falls back to most-recent when Ollama is unavailable.
"""
from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path
from typing import Optional

import httpx

from dialekt.llm._plugin_context import get_context

log = logging.getLogger("dialekt.few_shot")

FEW_SHOT_DB = Path.home() / ".dialekt" / "few_shots.db"
EMBED_MODEL = "nomic-embed-text:v1.5"
OLLAMA_URL = "http://localhost:11434"  # used as fallback if context unset
_MAX_QUESTION_CHARS = 1000
_MAX_ANSWER_CHARS = 2000


def _open() -> sqlite3.Connection:
    FEW_SHOT_DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(FEW_SHOT_DB))
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS few_shots (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            agent_id   TEXT NOT NULL,
            question   TEXT NOT NULL,
            answer     TEXT NOT NULL,
            embedding  TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_fs_agent ON few_shots(agent_id)")
    conn.commit()
    return conn


async def _embed(text: str) -> Optional[list[float]]:
    """Compute an embedding via Ollama's /api/embed.

    Honours Cloud GPU mode: when the active PluginContext has a relay
    configured, the call is routed through the relay (which exposes
    /api/embed as a transparent alias) with the Bearer header.
    """
    target = get_context().inference_target()
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.post(
                target.url("/api/embed"),
                headers=target.headers,
                json={"model": EMBED_MODEL, "input": text},
            )
            r.raise_for_status()
            return r.json().get("embeddings", [None])[0]
    except Exception:
        return None


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    mag_a = sum(x * x for x in a) ** 0.5
    mag_b = sum(x * x for x in b) ** 0.5
    if not mag_a or not mag_b:
        return 0.0
    return dot / (mag_a * mag_b)


async def save_interaction(agent_id: str, question: str, answer: str) -> None:
    """Persist a successful interaction; compute embedding asynchronously."""
    vec = await _embed(question)
    emb_json = json.dumps(vec) if vec is not None else None
    conn = _open()
    try:
        conn.execute(
            "INSERT INTO few_shots (agent_id, question, answer, embedding) VALUES (?,?,?,?)",
            (agent_id, question[:_MAX_QUESTION_CHARS], answer[:_MAX_ANSWER_CHARS], emb_json),
        )
        conn.commit()
    finally:
        conn.close()


async def get_few_shots(agent_id: str, query: str, k: int = 3) -> list[dict]:
    """
    Return up to k {question, answer} pairs for the agent ordered by semantic similarity.
    Falls back to most-recent k when Ollama is unreachable.
    """
    conn = _open()
    try:
        rows = conn.execute(
            "SELECT question, answer, embedding FROM few_shots "
            "WHERE agent_id = ? ORDER BY created_at DESC LIMIT 50",
            (agent_id,),
        ).fetchall()
    finally:
        conn.close()

    if not rows:
        return []

    q_vec = await _embed(query)
    if q_vec is not None:
        scored: list[tuple[float, str, str]] = []
        for row in rows:
            if row["embedding"]:
                try:
                    vec = json.loads(row["embedding"])
                    scored.append((_cosine(q_vec, vec), row["question"], row["answer"]))
                except Exception:
                    pass
        scored.sort(reverse=True)
        return [{"question": q, "answer": a} for _, q, a in scored[:k]]

    # Fallback: most recent without semantic ranking
    return [{"question": r["question"], "answer": r["answer"]} for r in rows[:k]]
