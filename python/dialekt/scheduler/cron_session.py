"""Emulate a chat session for one scheduled fire — without a real WebSocket.

A scheduled agent fires through this path:

    APScheduler tick
        → DialektScheduler.run_agent_job(agent_id)
            → CronSession(agent_id).run()
                → make_interpreter(agent)         # same factory as WS chat
                → asyncio.to_thread(itp.chat, message)   # blocking OI call
                → collect final assistant message
                → INSERT into scheduled_runs
            → deliver(result, agent)              # output.destination
            → log_event(kind="scheduled_run", ...)

We don't reuse the WebSocket chat handler for two reasons:

1. There's no client to stream to. Every event would land in /dev/null.
2. The WS handler holds session state in module-globals keyed on
   ``ws_id``; firing many agents in parallel would scribble over each
   other's state. CronSession owns its own ``session_id`` and uses no
   shared globals.

The session id is ``cron_<agent_id>_<unix_ts>`` — distinguishable in
audit logs from interactive sessions and idempotent for one fire.
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

import aiosqlite
import yaml as _yaml

log = logging.getLogger("dialekt.scheduler.cron_session")

# Hard wall-clock cap on a single scheduled run. Roadmap §3.2 calls for
# 5 minutes; matches the "scheduled" feel (these aren't realtime chats)
# without letting a runaway loop block the next fire.
DEFAULT_TIMEOUT_SECONDS = 300

# Default trigger.message when the manifest omits one. Localised in
# Russian because all KZ pilots run in Russian — the scheduled agent
# library (IBA, etc.) is the primary consumer.
DEFAULT_TRIGGER_MESSAGE = "Выполни свою задачу по расписанию."


@dataclass
class CronResult:
    """Outcome of a single scheduled fire — what the runner hands to ``deliver``."""
    run_id: str
    agent_id: str
    session_id: str
    status: str              # "success" | "failed" | "timeout"
    output: str
    error: str | None
    triggered_at: datetime
    completed_at: datetime
    duration_ms: int


class CronSession:
    def __init__(
        self,
        *,
        agent_id: str,
        agent: dict,
        db: aiosqlite.Connection,
        interpreter_factory: Callable[..., Any] | None = None,
        chat_runner: Callable[[Any, str], Awaitable[str]] | None = None,
        override_message: str | None = None,
        timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self.agent_id = agent_id
        self.agent = agent
        self.db = db
        self.run_id = str(uuid.uuid4())
        self.session_id = f"cron_{agent_id}_{int(time.time())}"
        self.override_message = override_message
        self.timeout_seconds = timeout_seconds
        # Indirection so tests can swap real OI with a deterministic stub.
        self._interpreter_factory = interpreter_factory
        self._chat_runner = chat_runner or _default_chat_runner

    @property
    def trigger_message(self) -> str:
        if self.override_message:
            return self.override_message
        manifest_yaml = self.agent.get("manifest_yaml") or ""
        if not manifest_yaml:
            return DEFAULT_TRIGGER_MESSAGE
        try:
            data = _yaml.safe_load(manifest_yaml) or {}
        except Exception as e:
            log.warning("agent %s manifest parse failed: %s", self.agent_id, e)
            return DEFAULT_TRIGGER_MESSAGE
        trigger = data.get("trigger") or {}
        msg = trigger.get("message")
        return msg.strip() if isinstance(msg, str) and msg.strip() else DEFAULT_TRIGGER_MESSAGE

    async def run(self) -> CronResult:
        triggered_at = datetime.now(timezone.utc)
        await self._record_started(triggered_at)
        message = self.trigger_message
        started = time.monotonic()
        status = "success"
        output = ""
        error: str | None = None

        try:
            factory = self._interpreter_factory or _resolve_default_factory()
            interpreter = factory(self.agent)
            output = await asyncio.wait_for(
                self._chat_runner(interpreter, message),
                timeout=self.timeout_seconds,
            )
        except asyncio.TimeoutError:
            status = "timeout"
            error = f"run exceeded {self.timeout_seconds}s timeout"
            log.warning("scheduled run %s for agent %s timed out", self.run_id, self.agent_id)
        except Exception as e:  # noqa: BLE001 — boundary catch
            status = "failed"
            error = f"{type(e).__name__}: {e}"
            log.exception("scheduled run %s for agent %s failed", self.run_id, self.agent_id)

        completed_at = datetime.now(timezone.utc)
        duration_ms = int((time.monotonic() - started) * 1000)
        await self._record_finished(status, output, error, completed_at, duration_ms)

        return CronResult(
            run_id=self.run_id,
            agent_id=self.agent_id,
            session_id=self.session_id,
            status=status,
            output=output,
            error=error,
            triggered_at=triggered_at,
            completed_at=completed_at,
            duration_ms=duration_ms,
        )

    async def _record_started(self, triggered_at: datetime) -> None:
        await self.db.execute(
            "INSERT INTO scheduled_runs "
            "(id, agent_id, session_id, status, triggered_at) "
            "VALUES (?, ?, ?, 'running', ?)",
            (self.run_id, self.agent_id, self.session_id, triggered_at.isoformat()),
        )
        await self.db.commit()

    async def _record_finished(
        self,
        status: str,
        output: str,
        error: str | None,
        completed_at: datetime,
        duration_ms: int,
    ) -> None:
        await self.db.execute(
            "UPDATE scheduled_runs SET status=?, output=?, error=?, "
            "completed_at=?, duration_ms=? WHERE id=?",
            (status, output, error, completed_at.isoformat(), duration_ms, self.run_id),
        )
        await self.db.commit()


def _resolve_default_factory():
    """Lazy import of ``server.make_interpreter`` so the scheduler module
    is importable in unit tests without standing up FastAPI."""
    from server import make_interpreter
    return make_interpreter


async def _default_chat_runner(interpreter: Any, message: str) -> str:
    """Run ``interpreter.chat(message)`` in a worker thread and extract
    the final assistant text. Open Interpreter's ``chat()`` is fully
    synchronous, so we offload it via ``to_thread`` and let the
    AsyncIOScheduler loop stay responsive.

    Output extraction: OI returns ``[{"role": ..., "type": ...,
    "content": ...}, ...]``. We concatenate every assistant message of
    type ``message`` (the natural-language replies); code blocks and
    tool outputs are skipped — those are run-time artefacts, the
    delivery surface wants the human-readable summary.
    """
    history = await asyncio.to_thread(interpreter.chat, message)
    if not isinstance(history, list):
        return str(history) if history is not None else ""
    chunks: list[str] = []
    for msg in history:
        if not isinstance(msg, dict):
            continue
        if msg.get("role") != "assistant":
            continue
        if msg.get("type") not in (None, "message"):
            continue
        content = msg.get("content")
        if isinstance(content, str) and content.strip():
            chunks.append(content.strip())
    return "\n\n".join(chunks)
