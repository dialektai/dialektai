"""How to handle scheduled fires we missed during a downtime window.

Two policies, declared per-agent in ``manifest.trigger.missed_run_policy``:

- ``run_on_startup`` (default) — when the scheduler boots, look at the
  most recent run for each agent and replay one fire if at least one
  cron iteration would have triggered between then and now. We replay
  *one*, not every missed fire — replaying ten weekly digests at once
  is noise, the user wants the "we caught up after the downtime" guarantee
  and a single fresh result.
- ``skip`` — ignore everything we missed. Next run happens at the next
  natural cron time.

This module is pure functions. The runner calls ``decide_missed_runs``
with the agents and their last-run timestamps; the result tells the
runner which agent ids to fire immediately on boot.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Iterable
from zoneinfo import ZoneInfo


class MissedRunPolicy(str, Enum):
    RUN_ON_STARTUP = "run_on_startup"
    SKIP = "skip"

    @classmethod
    def parse(cls, raw: str | None) -> "MissedRunPolicy":
        if not raw:
            return cls.RUN_ON_STARTUP
        try:
            return cls(raw)
        except ValueError:
            return cls.RUN_ON_STARTUP


@dataclass
class MissedAgent:
    """One agent the runner needs to know about during boot recovery."""
    agent_id: str
    cron: str
    timezone: str
    policy: MissedRunPolicy
    last_run_at: datetime | None  # last successful or attempted run


def decide_missed_runs(
    agents: Iterable[MissedAgent],
    *,
    now: datetime | None = None,
) -> list[str]:
    """Return the subset of ``agent_id``s whose policy + last-run gap
    means we should fire them immediately on startup.

    "Should fire" = policy is run_on_startup AND at least one cron
    iteration would have triggered between ``last_run_at`` and ``now``
    in the agent's declared timezone. Agents with no prior runs are
    fired (treats first boot as a missed run — useful for first install).

    Cron parsing uses ``croniter`` (already a dialekt dep via the
    manifest validator). If croniter chokes on the expression we treat
    it as "don't fire on startup" — bad cron means the schedule itself
    won't register, so silently dropping the catch-up call is safer
    than crashing the scheduler boot.
    """
    cur = now or datetime.now(timezone.utc)
    out: list[str] = []
    for ag in agents:
        if ag.policy is MissedRunPolicy.SKIP:
            continue
        try:
            tz = ZoneInfo(ag.timezone)
        except Exception:
            continue
        cur_local = cur.astimezone(tz)
        if ag.last_run_at is None:
            out.append(ag.agent_id)
            continue
        last_local = ag.last_run_at.astimezone(tz)
        try:
            from croniter import croniter
            it = croniter(ag.cron, last_local)
            next_fire = it.get_next(datetime)
        except Exception:
            continue
        if next_fire <= cur_local:
            out.append(ag.agent_id)
    return out
