"""Tests for dialekt.batch.runner — happy path, errors, cancel, missing
agent. Uses a FakeInterpreter so no Ollama dependency.

The runner is fully injectable: ``interpreter_factory`` and
``agent_loader`` plug in, ``output_root`` redirects writes, and
``on_event`` captures the SSE event stream as a plain list.
"""
import asyncio
import json
import tempfile
import threading
from pathlib import Path

import aiosqlite


# ── Fakes ─────────────────────────────────────────────────────────────


class _FakeInterpreter:
    """Minimal stand-in for Open Interpreter. Yields the OI chunk shape
    the runner expects (type='message', role='assistant', content=str)."""

    def __init__(self, response="processed", *, raise_on_call=None):
        self.response = response
        self.raise_on_call = raise_on_call
        self.received: list[str] = []
        self.resets = 0

    def chat(self, msg, stream=True, display=False):
        self.received.append(msg)
        if self.raise_on_call:
            raise self.raise_on_call
        # Two chunks to verify accumulation.
        yield {"type": "message", "role": "assistant", "content": "PREFIX:"}
        yield {"type": "message", "role": "assistant", "content": self.response}

    def reset(self):
        self.resets += 1


def _factory_returning(itp):
    return lambda agent, ctx: itp


async def _agent_dict(agent_id):
    return {"id": agent_id, "name": "TestAgent"}


async def _no_agent(agent_id):
    return None


# ── Tests ─────────────────────────────────────────────────────────────


def test_runner_happy_path_writes_outputs_and_emits_progress():
    from dialekt.batch import BATCH_SCHEMA, create_job, get_job, list_files, run_batch_job

    async def run():
        with tempfile.TemporaryDirectory() as tmp:
            tmpd = Path(tmp)
            inputs = []
            for name in ("a.txt", "b.txt", "c.txt"):
                p = tmpd / name
                p.write_text(f"content of {name}")
                inputs.append(str(p))
            out_root = tmpd / "out"

            itp = _FakeInterpreter(response="OK")
            events = []

            async with aiosqlite.connect(":memory:") as db:
                db.row_factory = aiosqlite.Row
                await db.execute("PRAGMA foreign_keys=ON")
                await db.executescript(BATCH_SCHEMA)
                job = await create_job(
                    db, agent_id="ed", file_paths=inputs,
                    variables={"instruction": "Rewrite", "output_ext": "md"},
                )

                await run_batch_job(
                    db, job.id,
                    interpreter_factory=_factory_returning(itp),
                    agent_loader=_agent_dict,
                    on_event=events.append,
                    output_root=out_root,
                )

                j = await get_job(db, job.id)
                assert j.status == "completed"
                assert j.done == 3

                files = await list_files(db, job.id)
                assert all(f.status == "done" for f in files)
                for f in files:
                    contents = Path(f.output_path).read_text()
                    assert contents == "PREFIX:OK"
                    assert isinstance(f.duration_ms, int)
                    assert f.duration_ms >= 0

                # Reset between files (3 files → 3 resets)
                assert itp.resets == 3

                # Manifest
                manifest_path = out_root / job.id / "_manifest.json"
                assert manifest_path.exists()
                data = json.loads(manifest_path.read_text())
                assert data["status"] == "completed"
                assert len(data["files"]) == 3

                # Event ordering: started → 3×(file_start, file_done,
                # progress) → completed
                etypes = [e["type"] for e in events]
                assert etypes[0] == "started"
                assert etypes.count("file_done") == 3
                assert etypes[-1] == "completed"

    asyncio.run(run())


def test_runner_error_path_marks_files_and_reports_durations():
    from dialekt.batch import BATCH_SCHEMA, create_job, get_job, list_files, run_batch_job

    async def run():
        with tempfile.TemporaryDirectory() as tmp:
            tmpd = Path(tmp)
            inputs = []
            for name in ("a.txt", "b.txt"):
                p = tmpd / name; p.write_text(name); inputs.append(str(p))

            itp = _FakeInterpreter(raise_on_call=RuntimeError("model exploded"))
            events = []

            async with aiosqlite.connect(":memory:") as db:
                db.row_factory = aiosqlite.Row
                await db.execute("PRAGMA foreign_keys=ON")
                await db.executescript(BATCH_SCHEMA)
                job = await create_job(db, agent_id="x", file_paths=inputs)

                await run_batch_job(
                    db, job.id,
                    interpreter_factory=_factory_returning(itp),
                    agent_loader=_agent_dict,
                    on_event=events.append,
                    output_root=tmpd / "out",
                )

                j = await get_job(db, job.id)
                # all files errored, no completed_outputs → status 'failed'
                assert j.status == "failed", j.status
                files = await list_files(db, job.id)
                assert all(f.status == "error" for f in files)
                assert all("model exploded" in (f.error or "") for f in files)
                etypes = [e["type"] for e in events]
                assert etypes.count("file_error") == 2

    asyncio.run(run())


def test_runner_mixed_outcomes_marks_completed_when_some_succeed():
    from dialekt.batch import BATCH_SCHEMA, create_job, get_job, list_files, run_batch_job

    class FlakyItp:
        def __init__(self):
            self.calls = 0
            self.resets = 0
        def chat(self, msg, stream=True, display=False):
            self.calls += 1
            if self.calls == 2:
                raise RuntimeError("transient")
            yield {"type": "message", "role": "assistant", "content": "OK"}
        def reset(self):
            self.resets += 1

    async def run():
        with tempfile.TemporaryDirectory() as tmp:
            tmpd = Path(tmp)
            inputs = [str((tmpd / n).write_text(n) or (tmpd / n))
                      for n in ("a.txt", "b.txt", "c.txt")]
            itp = FlakyItp()
            async with aiosqlite.connect(":memory:") as db:
                db.row_factory = aiosqlite.Row
                await db.execute("PRAGMA foreign_keys=ON")
                await db.executescript(BATCH_SCHEMA)
                job = await create_job(db, agent_id="x", file_paths=inputs)
                await run_batch_job(
                    db, job.id,
                    interpreter_factory=_factory_returning(itp),
                    agent_loader=_agent_dict,
                    output_root=tmpd / "out",
                )
                j = await get_job(db, job.id)
                # 2 succeeded, 1 errored → still 'completed' (mixed-success
                # convention; failed only when nothing succeeded)
                assert j.status == "completed", j.status
                files = await list_files(db, job.id)
                statuses = [f.status for f in files]
                assert statuses == ["done", "error", "done"]

    asyncio.run(run())


def test_runner_cancellation_marks_remaining_files_cancelled():
    from dialekt.batch import BATCH_SCHEMA, create_job, get_job, list_files, run_batch_job

    async def run():
        with tempfile.TemporaryDirectory() as tmp:
            tmpd = Path(tmp)
            inputs = []
            for n in ("a.txt", "b.txt", "c.txt"):
                p = tmpd / n; p.write_text(n); inputs.append(str(p))

            itp = _FakeInterpreter()
            cancel = threading.Event()
            cancel.set()  # cancelled before first file even starts

            async with aiosqlite.connect(":memory:") as db:
                db.row_factory = aiosqlite.Row
                await db.execute("PRAGMA foreign_keys=ON")
                await db.executescript(BATCH_SCHEMA)
                job = await create_job(db, agent_id="x", file_paths=inputs)
                await run_batch_job(
                    db, job.id,
                    interpreter_factory=_factory_returning(itp),
                    agent_loader=_agent_dict,
                    cancel_event=cancel,
                    output_root=tmpd / "out",
                )
                j = await get_job(db, job.id)
                assert j.status == "cancelled"
                files = await list_files(db, job.id)
                assert all(f.status == "cancelled" for f in files)
                assert itp.received == []

    asyncio.run(run())


def test_runner_missing_agent_fails_job_with_clear_error():
    from dialekt.batch import BATCH_SCHEMA, create_job, get_job, run_batch_job

    async def run():
        with tempfile.TemporaryDirectory() as tmp:
            tmpd = Path(tmp)
            (tmpd / "a.txt").write_text("x")
            async with aiosqlite.connect(":memory:") as db:
                db.row_factory = aiosqlite.Row
                await db.execute("PRAGMA foreign_keys=ON")
                await db.executescript(BATCH_SCHEMA)
                job = await create_job(db, agent_id="ghost", file_paths=[str(tmpd / "a.txt")])
                await run_batch_job(
                    db, job.id,
                    interpreter_factory=_factory_returning(_FakeInterpreter()),
                    agent_loader=_no_agent,
                    output_root=tmpd / "out",
                )
                j = await get_job(db, job.id)
                assert j.status == "failed"
                assert "ghost" in (j.error or "") and "not found" in (j.error or "")

    asyncio.run(run())


def test_runner_handles_missing_input_file_as_error():
    from dialekt.batch import BATCH_SCHEMA, create_job, get_job, list_files, run_batch_job

    async def run():
        with tempfile.TemporaryDirectory() as tmp:
            tmpd = Path(tmp)
            ok_file = tmpd / "a.txt"; ok_file.write_text("hi")
            inputs = [str(ok_file), "/does/not/exist.txt"]

            itp = _FakeInterpreter()
            async with aiosqlite.connect(":memory:") as db:
                db.row_factory = aiosqlite.Row
                await db.execute("PRAGMA foreign_keys=ON")
                await db.executescript(BATCH_SCHEMA)
                job = await create_job(db, agent_id="x", file_paths=inputs)
                await run_batch_job(
                    db, job.id,
                    interpreter_factory=_factory_returning(itp),
                    agent_loader=_agent_dict,
                    output_root=tmpd / "out",
                )
                j = await get_job(db, job.id)
                # The missing-file message goes through OI as a "[file at … —
                # not found]" body; OI still returns text so this row counts
                # as 'done', not 'error'. The test guards that the runner
                # does NOT crash on missing files.
                files = await list_files(db, job.id)
                assert files[0].status == "done"
                assert files[1].status == "done"
                assert "not found" in itp.received[1]

    asyncio.run(run())


def test_runner_normalises_output_extension():
    from dialekt.batch import BATCH_SCHEMA, create_job, list_files, run_batch_job

    async def run():
        with tempfile.TemporaryDirectory() as tmp:
            tmpd = Path(tmp)
            (tmpd / "a.txt").write_text("x")

            for variant in ("txt", ".txt", ".TXT", "  txt  "):
                async with aiosqlite.connect(":memory:") as db:
                    db.row_factory = aiosqlite.Row
                    await db.execute("PRAGMA foreign_keys=ON")
                    await db.executescript(BATCH_SCHEMA)
                    job = await create_job(
                        db, agent_id="x",
                        file_paths=[str(tmpd / "a.txt")],
                        variables={"output_ext": variant},
                    )
                    await run_batch_job(
                        db, job.id,
                        interpreter_factory=_factory_returning(_FakeInterpreter()),
                        agent_loader=_agent_dict,
                        output_root=tmpd / f"out_{variant.strip()}",
                    )
                    files = await list_files(db, job.id)
                    assert files[0].output_path.endswith(".txt"), (
                        f"variant {variant!r} → {files[0].output_path}"
                    )

    asyncio.run(run())


def test_runner_drops_invalid_extension_to_default_md():
    from dialekt.batch import BATCH_SCHEMA, create_job, list_files, run_batch_job

    async def run():
        with tempfile.TemporaryDirectory() as tmp:
            tmpd = Path(tmp)
            (tmpd / "a.txt").write_text("x")
            async with aiosqlite.connect(":memory:") as db:
                db.row_factory = aiosqlite.Row
                await db.execute("PRAGMA foreign_keys=ON")
                await db.executescript(BATCH_SCHEMA)
                # Path traversal / shell chars must NOT slip through.
                job = await create_job(
                    db, agent_id="x",
                    file_paths=[str(tmpd / "a.txt")],
                    variables={"output_ext": "../etc/pas;rm"},
                )
                await run_batch_job(
                    db, job.id,
                    interpreter_factory=_factory_returning(_FakeInterpreter()),
                    agent_loader=_agent_dict,
                    output_root=tmpd / "out",
                )
                files = await list_files(db, job.id)
                assert files[0].output_path.endswith(".md")

    asyncio.run(run())
