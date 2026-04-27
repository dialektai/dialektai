"""APScheduler wrapper that owns every scheduled-agent fire.

Lifecycle:

    server.lifespan
        → DialektScheduler(db).start()     # boot
            → reload() pulls scheduled agents from the agents table
            → each gets a CronTrigger via APScheduler
            → MissedRunPolicy.run_on_startup agents are fired once
              immediately to cover downtime gaps
        → … server runs …
        → DialektScheduler.stop()          # shutdown

Reload: callers (the CRUD handlers for /agents and /agents/import-yaml)
poke ``reload()`` after any change to a scheduled-agent manifest. We
diff the current registered jobs against the DB and add / replace /
remove as needed — the cheap option of "restart the whole scheduler"
loses in-flight runs.

Concurrency: one fire per agent at a time (``coalesce=True``,
``max_instances=1``). Two ticks landing while the first run is still
chugging through Open Interpreter just collapse to one — better than
piling up ten copies of the same digest.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable

import aiosqlite
import yaml as _yaml

from .cron_session import CronSession, CronResult
from .delivery import deliver, NOTIFICATIONS_SCHEMA
from .missed_run_policy import MissedAgent, MissedRunPolicy, decide_missed_runs

log = logging.getLogger("dialekt.scheduler.runner")

# v0.27 default tz for KZ pilots. Per-agent timezone in the manifest
# overrides this; the scheduler-wide setting only matters when an
# agent's manifest omits it (which the schema rejects, so this is
# really just a defensive default).
DEFAULT_TIMEZONE = "Asia/Almaty"

SCHEDULED_RUNS_SCHEMA = """
CREATE TABLE IF NOT EXISTS scheduled_runs (
    id                       TEXT PRIMARY KEY,
    agent_id                 TEXT NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    session_id               TEXT,
    status                   TEXT NOT NULL,
    triggered_at             TEXT NOT NULL DEFAULT (datetime('now')),
    completed_at             TEXT,
    duration_ms              INTEGER,
    output                   TEXT,
    error                    TEXT,
    delivery_status          TEXT,
    delivery_status_detail   TEXT,
    delivery_target          TEXT
);

CREATE INDEX IF NOT EXISTS idx_scheduled_runs_agent
    ON scheduled_runs(agent_id, triggered_at DESC);
CREATE INDEX IF NOT EXISTS idx_scheduled_runs_status
    ON scheduled_runs(status, triggered_at DESC);
""" + NOTIFICATIONS_SCHEMA


@dataclass
class _ParsedTrigger:
    """A scheduled trigger normalised into the fields APScheduler wants.

    The schema validator already enforces these are present and valid;
    this is just the YAML→struct conversion the runner needs at boot.
    """
    cron: str
    timezone: str
    policy: MissedRunPolicy


class DialektScheduler:
    def __init__(
        self,
        db: aiosqlite.Connection,
        *,
        default_timezone: str = DEFAULT_TIMEZONE,
        cron_session_factory=None,
        deliver_fn=None,
    ) -> None:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
        self.db = db
        self.default_timezone = default_timezone
        self._scheduler = AsyncIOScheduler(timezone=default_timezone)
        self._started = False
        # Indirection so tests can swap in deterministic stubs.
        self._cron_session_factory = cron_session_factory or _default_session_factory
        self._deliver = deliver_fn or deliver

    # ── lifecycle ────────────────────────────────────────────────────

    async def start(self) -> None:
        if self._started:
            return
        await self.reload()
        self._scheduler.start()
        self._started = True
        log.info("scheduler started; %d job(s) registered", len(self._scheduler.get_jobs()))
        # Catch-up pass — fire missed agents once. Done after start so
        # the catch-up runs go through the same path as scheduled fires.
        await self._fire_missed_runs()

    async def stop(self) -> None:
        if not self._started:
            return
        self._scheduler.shutdown(wait=False)
        self._started = False
        log.info("scheduler stopped")

    # ── reload / mutate ──────────────────────────────────────────────

    async def reload(self) -> dict:
        """Re-sync APScheduler jobs against the agents table.

        Returns ``{"added", "updated", "removed"}`` counts; the API
        endpoint surfaces these so the user sees what changed after a
        manifest edit.
        """
        from apscheduler.triggers.cron import CronTrigger

        existing_ids = {j.id for j in self._scheduler.get_jobs()}
        agents = await self._load_scheduled_agents()
        wanted_ids = {f"agent_{a['id']}" for a in agents}

        added = updated = 0
        for ag in agents:
            try:
                t = _parse_trigger(ag.get("manifest_yaml") or "")
            except Exception as e:
                log.error("scheduler: agent %s trigger invalid, skipping: %s", ag["id"], e)
                continue
            try:
                cron_trigger = CronTrigger.from_crontab(t.cron, timezone=t.timezone)
            except Exception as e:
                log.error("scheduler: agent %s cron %r invalid: %s", ag["id"], t.cron, e)
                continue
            job_id = f"agent_{ag['id']}"
            self._scheduler.add_job(
                func=self.run_agent_job,
                trigger=cron_trigger,
                id=job_id,
                kwargs={"agent_id": ag["id"]},
                misfire_grace_time=300,
                coalesce=True,
                max_instances=1,
                replace_existing=True,
            )
            if job_id in existing_ids:
                updated += 1
            else:
                added += 1

        removed = 0
        for stale in existing_ids - wanted_ids:
            try:
                self._scheduler.remove_job(stale)
                removed += 1
            except Exception:
                pass

        log.info("scheduler reload: +%d / ~%d / -%d", added, updated, removed)
        return {"added": added, "updated": updated, "removed": removed}

    # ── jobs ─────────────────────────────────────────────────────────

    async def run_agent_job(self, *, agent_id: str) -> CronResult:
        """The function APScheduler invokes on every cron tick."""
        agent = await self._load_agent(agent_id)
        if agent is None:
            log.warning("scheduler tick for missing agent %s — skipping", agent_id)
            raise RuntimeError(f"agent {agent_id} not found")
        return await self._fire_one(agent)

    async def run_now(self, agent_id: str, *, override_message: str | None = None) -> CronResult:
        """Manual fire path — wired to POST /agents/{id}/run-now. Same
        path as a cron tick, just bypasses the scheduler trigger.
        """
        agent = await self._load_agent(agent_id)
        if agent is None:
            raise RuntimeError(f"agent {agent_id} not found")
        return await self._fire_one(agent, override_message=override_message)

    async def status(self) -> dict:
        jobs = []
        for j in self._scheduler.get_jobs():
            agent_id = j.kwargs.get("agent_id") if isinstance(j.kwargs, dict) else None
            last = await self._last_run(agent_id) if agent_id else None
            # next_run_time is only populated once the scheduler is running;
            # callers (Settings UI) hit /scheduler/status during boot, so
            # we have to tolerate the unset case rather than AttributeError.
            next_at = getattr(j, "next_run_time", None)
            jobs.append({
                "agent_id": agent_id,
                "job_id": j.id,
                "next_run": next_at.isoformat() if next_at else None,
                "last_run_at": last["triggered_at"] if last else None,
                "last_status": last["status"] if last else None,
            })
        return {"running": self._started, "jobs": jobs}

    # ── internals ────────────────────────────────────────────────────

    async def _fire_one(self, agent: dict, *, override_message: str | None = None) -> CronResult:
        session = self._cron_session_factory(
            agent_id=agent["id"], agent=agent, db=self.db,
            override_message=override_message,
        )
        result = await session.run()

        delivery = await self._deliver(
            db=self.db, agent=agent, run_id=result.run_id,
            output=result.output, triggered_at=result.triggered_at,
        )
        await self.db.execute(
            "UPDATE scheduled_runs SET delivery_status=?, "
            "delivery_status_detail=?, delivery_target=? WHERE id=?",
            (delivery.status, delivery.detail, delivery.target, result.run_id),
        )
        await self.db.commit()

        await self._audit(result, delivery_status=delivery.status)
        return result

    async def _fire_missed_runs(self) -> None:
        agents = await self._load_scheduled_agents()
        missed_inputs: list[MissedAgent] = []
        for ag in agents:
            try:
                t = _parse_trigger(ag.get("manifest_yaml") or "")
            except Exception:
                continue
            last = await self._last_run(ag["id"])
            last_at = _parse_iso(last["triggered_at"]) if last else None
            missed_inputs.append(MissedAgent(
                agent_id=ag["id"], cron=t.cron, timezone=t.timezone,
                policy=t.policy, last_run_at=last_at,
            ))
        to_fire = decide_missed_runs(missed_inputs)
        for agent_id in to_fire:
            agent = await self._load_agent(agent_id)
            if agent is None:
                continue
            log.info("scheduler: catch-up run for agent %s", agent_id)
            try:
                await self._fire_one(agent)
            except Exception:
                log.exception("scheduler: catch-up run failed for %s", agent_id)

    async def _load_scheduled_agents(self) -> list[dict]:
        cur = await self.db.execute(
            "SELECT id, name, description, system_prompt, manifest_yaml, version, status "
            "FROM agents WHERE status != 'archived' AND manifest_yaml IS NOT NULL"
        )
        rows = await cur.fetchall()
        out = []
        for r in rows:
            d = dict(r)
            t = _peek_trigger_type(d.get("manifest_yaml") or "")
            if t == "scheduled":
                out.append(d)
        return out

    async def _load_agent(self, agent_id: str) -> dict | None:
        cur = await self.db.execute(
            "SELECT id, name, description, system_prompt, manifest_yaml, version, status "
            "FROM agents WHERE id=?",
            (agent_id,),
        )
        row = await cur.fetchone()
        return dict(row) if row else None

    async def _last_run(self, agent_id: str | None) -> dict | None:
        if not agent_id:
            return None
        cur = await self.db.execute(
            "SELECT id, status, triggered_at, completed_at, duration_ms "
            "FROM scheduled_runs WHERE agent_id=? "
            "ORDER BY triggered_at DESC, id DESC LIMIT 1",
            (agent_id,),
        )
        row = await cur.fetchone()
        return dict(row) if row else None

    async def _audit(self, result: CronResult, *, delivery_status: str) -> None:
        try:
            from dialekt.audit import log_event
            await log_event(
                self.db, kind="scheduled_run",
                action=result.status, result=result.status,
                target=result.agent_id, duration_ms=result.duration_ms,
                error_kind=("error" if result.error else None),
                extra={
                    "run_id": result.run_id,
                    "session_id": result.session_id,
                    "delivery_status": delivery_status,
                    "output_chars": len(result.output or ""),
                    "error_detail": result.error,
                },
            )
        except Exception:
            log.exception("audit log_event failed for run %s", result.run_id)


# ── module-level helpers ────────────────────────────────────────────────────

def _default_session_factory(**kwargs) -> CronSession:
    return CronSession(**kwargs)


def _peek_trigger_type(manifest_yaml: str) -> str | None:
    if not manifest_yaml:
        return None
    try:
        data = _yaml.safe_load(manifest_yaml) or {}
    except Exception:
        return None
    trigger = data.get("trigger") or {}
    t = trigger.get("type")
    return t if isinstance(t, str) else None


def _parse_trigger(manifest_yaml: str) -> _ParsedTrigger:
    """Pull cron / timezone / missed_run_policy out of a manifest. Schema
    accepts ``schedule`` (current name) and ``cron`` (the user-facing
    name in the docs) — read both, prefer ``schedule`` since that's
    what the validator emits.
    """
    data = _yaml.safe_load(manifest_yaml) or {}
    trigger = data.get("trigger") or {}
    cron = trigger.get("schedule") or trigger.get("cron")
    if not isinstance(cron, str) or not cron.strip():
        raise ValueError("trigger.schedule (cron expression) missing")
    tz = trigger.get("timezone") or DEFAULT_TIMEZONE
    if not isinstance(tz, str):
        raise ValueError("trigger.timezone must be a string")
    policy = MissedRunPolicy.parse(trigger.get("missed_run_policy"))
    return _ParsedTrigger(cron=cron.strip(), timezone=tz, policy=policy)


def _parse_iso(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt
