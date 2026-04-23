"""Tests for Goal 8.5 — few-shot memory (save + retrieve)."""
import json
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

import dialekt.llm.few_shot_memory as fsm


@pytest.fixture(autouse=True)
def tmp_db(tmp_path, monkeypatch):
    """Redirect the few-shot DB to a temp file for each test."""
    monkeypatch.setattr(fsm, "FEW_SHOT_DB", tmp_path / "few_shots.db")
    yield


def test_open_creates_table(tmp_path, monkeypatch):
    monkeypatch.setattr(fsm, "FEW_SHOT_DB", tmp_path / "few_shots.db")
    conn = fsm._open()
    tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    names = [r[0] for r in tables]
    assert "few_shots" in names
    conn.close()


def test_cosine_identical_vectors():
    v = [1.0, 0.0, 0.0]
    assert abs(fsm._cosine(v, v) - 1.0) < 1e-6


def test_cosine_orthogonal_vectors():
    a = [1.0, 0.0]
    b = [0.0, 1.0]
    assert abs(fsm._cosine(a, b)) < 1e-6


def test_cosine_zero_vector():
    assert fsm._cosine([0.0, 0.0], [1.0, 0.0]) == 0.0


@pytest.mark.asyncio
async def test_save_interaction_stores_row(monkeypatch):
    monkeypatch.setattr(fsm, "_embed", AsyncMock(return_value=None))
    await fsm.save_interaction("agent-1", "What is SQL?", "SQL is a query language.")
    conn = fsm._open()
    rows = conn.execute("SELECT * FROM few_shots WHERE agent_id='agent-1'").fetchall()
    conn.close()
    assert len(rows) == 1
    assert rows[0]["question"] == "What is SQL?"
    assert rows[0]["answer"] == "SQL is a query language."


@pytest.mark.asyncio
async def test_save_interaction_stores_embedding(monkeypatch):
    fake_vec = [0.1, 0.2, 0.3]
    monkeypatch.setattr(fsm, "_embed", AsyncMock(return_value=fake_vec))
    await fsm.save_interaction("agent-2", "q", "a")
    conn = fsm._open()
    rows = conn.execute("SELECT embedding FROM few_shots WHERE agent_id='agent-2'").fetchall()
    conn.close()
    assert len(rows) == 1
    assert json.loads(rows[0]["embedding"]) == fake_vec


@pytest.mark.asyncio
async def test_get_few_shots_empty_db(monkeypatch):
    monkeypatch.setattr(fsm, "_embed", AsyncMock(return_value=None))
    result = await fsm.get_few_shots("no-agent", "any query")
    assert result == []


@pytest.mark.asyncio
async def test_get_few_shots_returns_most_recent_when_no_embeddings(monkeypatch):
    monkeypatch.setattr(fsm, "_embed", AsyncMock(return_value=None))
    for i in range(5):
        await fsm.save_interaction("agent-3", f"Question {i}", f"Answer {i}")
    result = await fsm.get_few_shots("agent-3", "query")
    assert len(result) <= 3
    assert all("question" in r and "answer" in r for r in result)


@pytest.mark.asyncio
async def test_get_few_shots_semantic_ranking(monkeypatch):
    # Store two interactions with distinct fake embeddings
    monkeypatch.setattr(fsm, "_embed", AsyncMock(return_value=None))
    await fsm.save_interaction("agent-4", "cats", "meow")
    await fsm.save_interaction("agent-4", "dogs", "woof")

    # Now simulate embeddings on retrieval: query close to "cats"
    cat_vec = [1.0, 0.0]
    dog_vec = [0.0, 1.0]
    query_vec = [0.9, 0.1]  # closer to cat

    # Patch embeddings stored in DB manually
    conn = fsm._open()
    rows = conn.execute("SELECT id, question FROM few_shots WHERE agent_id='agent-4'").fetchall()
    for row in rows:
        vec = cat_vec if row["question"] == "cats" else dog_vec
        conn.execute("UPDATE few_shots SET embedding=? WHERE id=?", (json.dumps(vec), row["id"]))
    conn.commit()
    conn.close()

    monkeypatch.setattr(fsm, "_embed", AsyncMock(return_value=query_vec))
    result = await fsm.get_few_shots("agent-4", "what do cats say?", k=1)
    assert len(result) == 1
    assert result[0]["question"] == "cats"


@pytest.mark.asyncio
async def test_question_truncated_to_max_chars(monkeypatch):
    monkeypatch.setattr(fsm, "_embed", AsyncMock(return_value=None))
    long_q = "x" * 2000
    await fsm.save_interaction("agent-5", long_q, "short answer")
    conn = fsm._open()
    row = conn.execute("SELECT question FROM few_shots WHERE agent_id='agent-5'").fetchone()
    conn.close()
    assert len(row["question"]) == fsm._MAX_QUESTION_CHARS


@pytest.mark.asyncio
async def test_answer_truncated_to_max_chars(monkeypatch):
    monkeypatch.setattr(fsm, "_embed", AsyncMock(return_value=None))
    long_a = "y" * 5000
    await fsm.save_interaction("agent-6", "short q", long_a)
    conn = fsm._open()
    row = conn.execute("SELECT answer FROM few_shots WHERE agent_id='agent-6'").fetchone()
    conn.close()
    assert len(row["answer"]) == fsm._MAX_ANSWER_CHARS
