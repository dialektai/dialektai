"""Batch runner — execute one job, file by file, through Open Interpreter.

Architecture
------------
A batch job runs in the FastAPI event loop as an asyncio task. For each
file the runner spins a daemon thread (the same way ``ws_chat`` does)
to call ``itp.chat(...)``, collects the assistant text output, writes
it to disk, and updates SQLite.

The runner is **serialised** with interactive chat through
``_BATCH_LOCK``: dialekt's OI is a module-level singleton (see
``server.make_interpreter``), so concurrent chat + batch would clobber
each other's system_message and model. Pilot scope accepts this — a
batch typically runs in a quiet window. Multi-tenant cloud tenants get
their own process, so this lock is only relevant on the desktop.

Cancellation
------------
The endpoint sets a ``threading.Event`` on the job. The runner checks
it before each file. Once tripped, in-flight OI thread is allowed to
finish (we don't kill mid-call — risk of half-written output / model
in undefined state); remaining files become ``cancelled``; the job
status flips to ``cancelled``.

Output
------
``~/.dialekt/batch/<job_id>/<input_basename>.<ext>`` with extension
controlled by ``variables.output_ext`` (defaults to ``.md``). A
``_manifest.json`` summary is written alongside on completion.
"""
from __future__ import annotations

import asyncio
import contextvars
import json
import logging
import threading
import time
from pathlib import Path
from typing import Any, Awaitable, Callable

import aiosqlite

from . import job as job_mod


log = logging.getLogger(__name__)


# Path the runner writes outputs to. Override in tests via the
# ``output_root`` arg to ``run_batch_job``.
DEFAULT_OUTPUT_ROOT = Path.home() / ".dialekt" / "batch"

# OI is a module-level singleton in dialekt; serialise batch with chat.
_BATCH_LOCK = asyncio.Lock()


# Event payloads emitted to ``on_event``. Plain dicts — the SSE endpoint
# JSON-encodes them.
EventCallback = Callable[[dict[str, Any]], None] | None


# ── Public API ────────────────────────────────────────────────────────


async def run_batch_job(
    db: aiosqlite.Connection,
    job_id: str,
    *,
    interpreter_factory: Callable[[dict | None, dict | None], Any] | None = None,
    agent_loader: Callable[[str], Awaitable[dict | None]] | None = None,
    on_event: EventCallback = None,
    cancel_event: threading.Event | None = None,
    output_root: Path | None = None,
) -> None:
    """Run a previously-created job to completion.

    All collaborators are injectable so the runner is unit-testable
    without spinning up Ollama / FastAPI:

    - ``interpreter_factory(agent_dict, agent_context)`` -> interpreter
       Defaults to ``server.make_interpreter`` lazy-imported at runtime.
       The interpreter must expose ``chat(message, stream=True,
       display=False)`` returning an iterable of OI chunk dicts, and
       ``reset()``.
    - ``agent_loader(agent_id)`` -> agent dict or None
       Defaults to ``server.db_get_agent``. Returning None fails the
       job with a clear error.
    - ``on_event(event_dict)`` — sync callback; SSE endpoint pushes
       events from here to subscribers. Failures in the callback are
       swallowed (best-effort delivery).
    - ``cancel_event`` — threading.Event; checked between files. The
       endpoint also marks DB status to 'cancelled' to belt-and-braces.
    - ``output_root`` — override for tests.
    """
    out_root = (output_root or DEFAULT_OUTPUT_ROOT).expanduser()
    cancel_event = cancel_event or threading.Event()

    job = await job_mod.get_job(db, job_id)
    if job is None:
        raise ValueError(f"job {job_id} does not exist")

    factory, loader = await _resolve_collaborators(interpreter_factory, agent_loader)

    async with _BATCH_LOCK:
        await job_mod.set_job_status(db, job_id, "running")
        _emit(on_event, {"type": "started", "job_id": job_id, "total": job.total})

        agent = await loader(job.agent_id)
        if agent is None:
            err = f"agent {job.agent_id} not found"
            await job_mod.set_job_error(db, job_id, err)
            _emit(on_event, {"type": "failed", "job_id": job_id, "error": err})
            return

        try:
            itp = factory(agent, None)
        except Exception as exc:
            err = f"interpreter init failed: {exc}"
            log.exception("batch %s — interpreter init failed", job_id)
            await job_mod.set_job_error(db, job_id, err)
            _emit(on_event, {"type": "failed", "job_id": job_id, "error": err})
            return

        instruction = (job.variables.get("instruction") or "").strip() or _DEFAULT_INSTRUCTION
        output_ext = _normalise_ext(job.variables.get("output_ext"))

        out_dir = out_root / job_id
        out_dir.mkdir(parents=True, exist_ok=True)

        files = await job_mod.list_files(db, job_id)
        completed_outputs: list[dict[str, Any]] = []
        any_error = False

        for f in files:
            if cancel_event.is_set():
                await job_mod.record_file_cancelled(db, f.id)
                _emit(on_event, {"type": "file_cancelled", "ordinal": f.ordinal})
                continue

            await job_mod.record_file_started(db, f.id)
            _emit(on_event, {
                "type": "file_start", "ordinal": f.ordinal, "name": f.input_name,
            })

            t0 = time.monotonic()
            try:
                user_msg = _build_user_message(instruction, f.input_path, f.input_name)
                output_text = _run_one_file(itp, user_msg)

                out_path = out_dir / f"{Path(f.input_name).stem}{output_ext}"
                out_path.write_text(output_text, encoding="utf-8")
                duration_ms = int((time.monotonic() - t0) * 1000)
                await job_mod.record_file_done(
                    db, f.id, output_path=str(out_path), duration_ms=duration_ms
                )
                completed_outputs.append({
                    "ordinal": f.ordinal,
                    "name": f.input_name,
                    "output": str(out_path),
                    "duration_ms": duration_ms,
                })
                done = await job_mod.increment_done(db, job_id)
                _emit(on_event, {
                    "type": "file_done", "ordinal": f.ordinal,
                    "output_path": str(out_path), "duration_ms": duration_ms,
                })
                _emit(on_event, {
                    "type": "progress", "done": done, "total": job.total,
                })
            except Exception as exc:
                duration_ms = int((time.monotonic() - t0) * 1000)
                msg = str(exc)
                log.exception("batch %s — file %s failed", job_id, f.input_name)
                await job_mod.record_file_error(
                    db, f.id, message=msg, duration_ms=duration_ms
                )
                done = await job_mod.increment_done(db, job_id)
                any_error = True
                _emit(on_event, {
                    "type": "file_error", "ordinal": f.ordinal, "error": msg,
                })
                _emit(on_event, {
                    "type": "progress", "done": done, "total": job.total,
                })
            finally:
                _safe_reset(itp)

        # Final state
        final_job = await job_mod.get_job(db, job_id)
        any_cancelled = any(
            ff.status == "cancelled"
            for ff in await job_mod.list_files(db, job_id)
        )
        if cancel_event.is_set() or any_cancelled:
            final_status = "cancelled"
        elif any_error and not completed_outputs:
            final_status = "failed"
        else:
            final_status = "completed"

        await job_mod.set_job_status(db, job_id, final_status)
        # Re-fetch so the manifest reflects the terminal status / done count.
        final_job = await job_mod.get_job(db, job_id)
        _write_manifest(out_dir, final_job, completed_outputs, any_error)
        _emit(on_event, {
            "type": final_status,
            "job_id": job_id,
            "done": final_job.done if final_job else 0,
            "total": final_job.total if final_job else 0,
        })


# ── Internals ─────────────────────────────────────────────────────────


_DEFAULT_INSTRUCTION = (
    "Process the attached file according to your system prompt. Return "
    "only the result; no preamble."
)

_VALID_EXT_CHARS = set("abcdefghijklmnopqrstuvwxyz0123456789")


def _normalise_ext(raw: Any) -> str:
    """Coerce a user-supplied extension to '.foo'. Defaults to '.md'."""
    if not isinstance(raw, str) or not raw.strip():
        return ".md"
    ext = raw.strip().lstrip(".").lower()
    if not ext or any(c not in _VALID_EXT_CHARS for c in ext):
        return ".md"
    return f".{ext[:8]}"


def _build_user_message(instruction: str, input_path: str, input_name: str) -> str:
    """Inline the file's text into the user message for OI.

    Mirrors ``server.preprocess_content`` for the @file: case but is
    self-contained so the runner does not pull in the FastAPI module.
    Binary files are referenced by path with a hint so the agent's
    Python tool-use can read them if it knows how (PDF/DOCX agents
    plug in their own extractors). For pilot scope the happy path is
    plain-text inputs.
    """
    body: str
    p = Path(input_path)
    if not p.exists():
        body = f"[file at {input_path} — not found]"
    else:
        try:
            raw = p.read_bytes()
            text = raw.decode("utf-8")
            if len(text) > 60_000:
                text = text[:60_000] + f"\n... [truncated — full file is {len(text)} chars]"
            ext = p.suffix.lstrip(".") or "text"
            body = f"--- {input_name} ---\n```{ext}\n{text}\n```"
        except UnicodeDecodeError:
            body = (
                f"--- {input_name} --- [binary file, path: {input_path}]\n"
                "If this is a format your tools can read (PDF, DOCX, etc.), "
                "extract the text first. Otherwise, summarise what the file is."
            )
    return f"{instruction}\n\n{body}"


def _run_one_file(itp: Any, user_msg: str) -> str:
    """Run OI on one message in a thread and return the assistant text.

    Mirrors the buffer-collection loop in ``server.ws_chat`` but
    synchronous and silent — we don't stream chunks to a WS, we just
    accumulate the final message. ContextVar copy follows the same
    pattern v0.20 ws_chat uses for MCP runtime resolution.
    """
    text_buf: list[str] = []
    err_holder: list[BaseException | None] = [None]

    def runner():
        try:
            for chunk in itp.chat(user_msg, stream=True, display=False):
                ctype = chunk.get("type", "")
                crole = chunk.get("role", "")
                ccontent = chunk.get("content", "")
                if ctype == "message" and crole == "assistant" and isinstance(ccontent, str):
                    text_buf.append(ccontent)
        except BaseException as exc:  # noqa: BLE001 — re-raised below
            err_holder[0] = exc

    ctx_copy = contextvars.copy_context()
    t = threading.Thread(target=lambda: ctx_copy.run(runner), daemon=True)
    t.start()
    t.join()

    if err_holder[0] is not None:
        raise err_holder[0]
    return "".join(text_buf).strip()


def _safe_reset(itp: Any) -> None:
    try:
        itp.reset()
    except Exception:
        log.debug("interpreter reset failed; continuing", exc_info=True)


def _emit(cb: EventCallback, event: dict[str, Any]) -> None:
    if cb is None:
        return
    try:
        cb(event)
    except Exception:
        log.debug("on_event callback raised; ignored", exc_info=True)


def _write_manifest(
    out_dir: Path,
    job: job_mod.Job | None,
    outputs: list[dict[str, Any]],
    any_error: bool,
) -> None:
    summary = {
        "job_id": job.id if job else None,
        "agent_id": job.agent_id if job else None,
        "status": job.status if job else None,
        "total": job.total if job else 0,
        "done": job.done if job else 0,
        "had_errors": any_error,
        "files": outputs,
    }
    try:
        (out_dir / "_manifest.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception:
        log.debug("manifest write failed", exc_info=True)


async def _resolve_collaborators(
    factory: Callable[[dict | None, dict | None], Any] | None,
    loader: Callable[[str], Awaitable[dict | None]] | None,
) -> tuple[Callable[[dict | None, dict | None], Any], Callable[[str], Awaitable[dict | None]]]:
    if factory is not None and loader is not None:
        return factory, loader

    # Lazy import — avoids pulling FastAPI app on package import.
    if factory is None:
        from server import make_interpreter as _mk
        factory = _mk
    if loader is None:
        from server import db_get_agent as _ld
        loader = _ld
    return factory, loader
