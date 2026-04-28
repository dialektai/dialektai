"""Scheduling primitives for dialekt agents.

Public API:

- :mod:`constraint_solver` — distribute N programs × K dates each
  across a year's working days, honouring KZ holidays, format
  alternation (in-person ↔ online), per-block anti-clustering,
  and even distribution across windows.
"""

from .catalog import CatalogLoadError, load_catalog, to_dicts
from .constraint_solver import (
    DistributionResult,
    ProgramSpec,
    ScheduleConstraintError,
    distribute_schedule,
)

__all__ = [
    "CatalogLoadError",
    "DistributionResult",
    "ProgramSpec",
    "ScheduleConstraintError",
    "distribute_schedule",
    "load_catalog",
    "to_dicts",
]
