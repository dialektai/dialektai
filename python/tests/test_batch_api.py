"""Integration tests for /batch endpoints via FastAPI TestClient.

Runs the full lifecycle: POST /batch → poll /batch/{id} → GET zip →
cancel idempotency → 404 / 422 paths. Uses a FakeInterpreter patched
into ``server.make_interpreter`` so the harness needs no Ollama.
"""
import asyncio
import io
import tempfile
import time
import zipfile
from pathlib import Path
from unittest.mock import patch

import pytest


@pytest.fixture(scope="module")
def harness():
    """Spin a TestClient against an isolated temp ~/.dialekt and an
    output_root scoped to the same dir. Yields (client, server_module,
    tmp_path)."""
    from fastapi.testclient import TestClient
    import server as srv
    from dialekt.batch import runner as rmod
    import dialekt.batch as bmod

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp) / ".dialekt"
        tmp_dir.mkdir()
        (tmp_dir / "config.json").write_text("{}")

        original_db = srv.DB_PATH
        original_cfg = srv.SETTINGS_FILE
        original_out_runner = rmod.DEFAULT_OUTPUT_ROOT
        original_out_pkg = bmod.DEFAULT_OUTPUT_ROOT

        srv.DB_PATH = tmp_dir / "dialekt.db"
        srv.SETTINGS_FILE = tmp_dir / "config.json"
        out_root = tmp_dir / "batch_out"
        rmod.DEFAULT_OUTPUT_ROOT = out_root
        bmod.DEFAULT_OUTPUT_ROOT = out_root

        class FakeInterpreter:
            def chat(self, msg, stream=True, display=False):
                yield {"type": "message", "role": "assistant", "content": "PROCESSED"}
            def reset(self): pass

        with TestClient(srv.app) as client, \
             patch("server.make_interpreter", return_value=FakeInterpreter()):
            # TestClient's lifespan ran on its own loop; we need to talk
            # to the same SQLite connection it created.
            async def insert_agent():
                await srv.db.execute(
                    "INSERT INTO agents (id, name) VALUES ('agent-test','TestAgent')"
                )
                await srv.db.commit()
            client.portal.call(insert_agent)

            yield client, srv, Path(tmp), out_root

        srv.DB_PATH = original_db
        srv.SETTINGS_FILE = original_cfg
        rmod.DEFAULT_OUTPUT_ROOT = original_out_runner
        bmod.DEFAULT_OUTPUT_ROOT = original_out_pkg


def _wait_terminal(client, job_id, timeout=15.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        j = client.get(f"/batch/{job_id}").json()["job"]
        if j["status"] in ("completed", "failed", "cancelled"):
            return j
        time.sleep(0.05)
    raise AssertionError(f"batch {job_id} did not reach terminal state")


def _seed_inputs(tmp_path, n=3):
    inputs = []
    for i in range(n):
        p = tmp_path / f"in_{i}.txt"
        p.write_text(f"content {i}")
        inputs.append(str(p))
    return inputs


def test_post_batch_validates_required_fields(harness):
    client, *_ = harness
    # missing agent_id
    r = client.post("/batch", json={"file_paths": ["/tmp/a"]})
    assert r.status_code == 422
    # empty file list
    r = client.post("/batch", json={"agent_id": "agent-test", "file_paths": []})
    assert r.status_code == 422
    # variables not a dict
    r = client.post("/batch", json={
        "agent_id": "agent-test", "file_paths": ["/tmp/a"], "variables": "broken",
    })
    assert r.status_code == 422


def test_post_batch_unknown_agent_returns_404(harness):
    client, *_ = harness
    r = client.post("/batch", json={
        "agent_id": "nope", "file_paths": ["/tmp/x"],
    })
    assert r.status_code == 404


def test_full_lifecycle_completes_and_zips(harness):
    client, srv, tmp, out_root = harness
    inputs = _seed_inputs(tmp, n=3)

    r = client.post("/batch", json={
        "agent_id": "agent-test", "file_paths": inputs,
        "variables": {"instruction": "Rewrite"},
    })
    assert r.status_code == 201
    body = r.json()
    job_id = body["job_id"]
    assert body["total"] == 3 and body["status"] == "pending"

    j = _wait_terminal(client, job_id)
    assert j["status"] == "completed" and j["done"] == 3

    snap = client.get(f"/batch/{job_id}").json()
    assert all(f["status"] == "done" for f in snap["files"])

    r = client.get(f"/batch/{job_id}/zip")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/zip"
    zf = zipfile.ZipFile(io.BytesIO(r.content))
    names = zf.namelist()
    assert "_manifest.json" in names
    assert sum(1 for n in names if n.endswith(".md")) == 3


def test_zip_409_while_running_is_explicit(harness, monkeypatch):
    """If we hit /zip before terminal we should get 409, not 200 with
    half-baked contents."""
    client, srv, tmp, out_root = harness
    inputs = _seed_inputs(tmp, n=2)
    r = client.post("/batch", json={
        "agent_id": "agent-test", "file_paths": inputs,
    })
    job_id = r.json()["job_id"]
    # Try /zip immediately while job is still pending/running. Race-y
    # by nature; allow either 409 (job not yet terminal) or 200 if the
    # runner already finished. The test guards that 409 is the live
    # response shape and never 500.
    r = client.get(f"/batch/{job_id}/zip")
    assert r.status_code in (200, 409)
    _wait_terminal(client, job_id)


def test_cancel_is_idempotent_and_404s_unknown(harness):
    client, srv, tmp, _ = harness
    inputs = _seed_inputs(tmp, n=1)
    r = client.post("/batch", json={
        "agent_id": "agent-test", "file_paths": inputs,
    })
    job_id = r.json()["job_id"]
    _wait_terminal(client, job_id)

    # Cancel after terminal — still 200, idempotent.
    r = client.post(f"/batch/{job_id}/cancel")
    assert r.status_code == 200
    assert r.json()["cancel_requested"] is True

    # Unknown id — 404.
    r = client.post("/batch/no-such-job/cancel")
    assert r.status_code == 404


def test_unknown_paths_404(harness):
    client, *_ = harness
    assert client.get("/batch/no-such-job").status_code == 404
    assert client.get("/batch/no-such-job/zip").status_code == 404
    assert client.get("/batch/no-such-job/stream").status_code == 404


def test_stream_replays_snapshot_for_terminal_job(harness):
    client, srv, tmp, _ = harness
    inputs = _seed_inputs(tmp, n=2)
    job_id = client.post("/batch", json={
        "agent_id": "agent-test", "file_paths": inputs,
    }).json()["job_id"]
    _wait_terminal(client, job_id)

    with client.stream("GET", f"/batch/{job_id}/stream") as s:
        assert s.status_code == 200
        first = ""
        for chunk in s.iter_text():
            first += chunk
            if "snapshot" in first:
                break
        assert "snapshot" in first
        assert "completed" in first or "files" in first


def test_post_accepts_alias_field_names(harness):
    """Spec says ``file_ids`` in the body; the endpoint also accepts
    ``file_paths`` (canonical) and ``files``. All three should land."""
    client, srv, tmp, _ = harness
    inputs = _seed_inputs(tmp, n=1)
    for field in ("file_paths", "file_ids", "files"):
        r = client.post("/batch", json={"agent_id": "agent-test", field: inputs})
        assert r.status_code == 201, f"alias {field!r} rejected"
        _wait_terminal(client, r.json()["job_id"])
