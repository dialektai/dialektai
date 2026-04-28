"""Scheduled-trigger runtime for dialekt agents.

Roadmap section 3.2: agents whose manifest declares
``trigger.type: scheduled`` need a runtime that fires their
``trigger.message`` against ``make_interpreter`` on a cron schedule
without opening a real WebSocket session. This package owns that
runtime.

Public surface:

- ``DialektScheduler`` — APScheduler wrapper. Boots inside the FastAPI
  ``lifespan``, reloads agents from the ``agents`` table, registers a
  ``CronTrigger`` per scheduled agent. Exposes ``reload()``,
  ``run_now()``, ``status()``.
- ``CronSession`` — emulates a chat turn for one scheduled fire:
  ``make_interpreter(agent)`` → ``interpreter.chat(message)`` →
  collect output → write a ``scheduled_runs`` row.
- ``deliver`` — dispatch the result to ``output.destination``
  (``notification`` / ``email_or_telegram`` / ``filesystem``).
- ``MissedRunPolicy`` — ``run_on_startup`` (default) catches up
  missed fires after a downtime; ``skip`` ignores them.

Persistence:

- APScheduler uses ``MemoryJobStore`` — every scheduled agent is
  re-registered from the agents table on boot, so a SQL job store
  would only duplicate state.
- Run *history* persists in the ``scheduled_runs`` table — that's
  what the Settings UI reads for the runs panel.
"""

from .runner import DialektScheduler, SCHEDULED_RUNS_SCHEMA, AGENT_RSS_STATE_SCHEMA
from .cron_session import CronSession, CronResult
from .delivery import deliver, DeliveryResult
from .missed_run_policy import MissedRunPolicy, decide_missed_runs

__all__ = [
    "DialektScheduler",
    "SCHEDULED_RUNS_SCHEMA",
    "AGENT_RSS_STATE_SCHEMA",
    "CronSession",
    "CronResult",
    "deliver",
    "DeliveryResult",
    "MissedRunPolicy",
    "decide_missed_runs",
]
