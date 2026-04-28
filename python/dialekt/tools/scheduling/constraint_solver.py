"""Schedule constraint solver for IBA-style program calendars.

Problem (TZ #4):

    Each program needs ``min_dates_per_program`` dates per year for
    a given format (in-person / online). The dates must be:

    - working days (weekdays, no KZ public holidays, government
      transfer-of-rest aware)
    - distributed evenly across the year — no clustering inside
      one month
    - not clashing on the same day with too many other programs
      from the same block (configurable cap)
    - deterministic: re-running with the same input yields the
      same output (seeded RNG)

For an IBA-shaped problem (≈300 programs × 3 dates × 2 formats =
1800 events, ≈250 working days/year ≈ 7 events/day average), a
pure-greedy assignment hits dead-ends; we use a windowed greedy
plus single-step backtracking — assign one (program, window)
pair at a time, scoring candidate dates by how full the day
already is, and rolling back to the next-best candidate when a
constraint is violated. No CSP framework needed at this scale.

The solver is pure-Python, no third-party deps.
"""
from __future__ import annotations

import datetime as dt
import logging
import random
from dataclasses import dataclass, field
from typing import Iterable, Optional

from dialekt.tools.calendar import kz_holidays

log = logging.getLogger("dialekt.tools.scheduling.constraint_solver")


class ScheduleConstraintError(ValueError):
    """Raised when the input is structurally invalid (not when a
    constraint is unsatisfiable — that surfaces as ``unscheduled``
    in the result so the caller can decide what to do)."""


@dataclass(frozen=True)
class ProgramSpec:
    """One program needing a schedule.

    ``block`` is the soft anti-clustering key. Programs in the same
    block compete for slot space on each day; a 'finance' block
    with 10 programs landing all on the same Tuesday would be a
    bug, so the solver caps how many programs from one block can
    share a single date.
    """
    id: str
    name: str
    block: Optional[str] = None


@dataclass
class DistributionResult:
    """Output of :func:`distribute_schedule`.

    ``schedule[program_id] = ["2026-04-28", ...]`` — list of ISO
    date strings, length == ``min_dates_per_program`` when fully
    scheduled, shorter when constraints couldn't be met.
    ``unscheduled[program_id] = N`` reports how many dates per
    program the solver couldn't place. Empty dict on full success.
    """
    schedule: dict[str, list[str]] = field(default_factory=dict)
    unscheduled: dict[str, int] = field(default_factory=dict)
    daily_load: dict[str, int] = field(default_factory=dict)

    @property
    def fully_scheduled(self) -> bool:
        return not self.unscheduled

    def to_dict(self) -> dict:
        return {
            "schedule": dict(self.schedule),
            "unscheduled": dict(self.unscheduled),
            "daily_load": dict(self.daily_load),
            "fully_scheduled": self.fully_scheduled,
        }


def _validate_inputs(
    programs: Iterable,
    year: int,
    min_dates_per_program: int,
    n_windows: int,
    block_max_per_day: int,
) -> list[ProgramSpec]:
    """Coerce + validate. Programs may arrive as ProgramSpec or
    dicts; we normalise to a list of ProgramSpec and bubble up
    structural problems early."""
    if not isinstance(year, int) or not (2026 <= year <= 2030):
        raise ScheduleConstraintError(
            f"year must be int in [2026, 2030] (curated holiday range), got {year!r}"
        )
    if not isinstance(min_dates_per_program, int) or min_dates_per_program <= 0:
        raise ScheduleConstraintError(
            "min_dates_per_program must be a positive int"
        )
    if not isinstance(n_windows, int) or n_windows <= 0:
        raise ScheduleConstraintError("n_windows must be a positive int")
    if min_dates_per_program > n_windows:
        raise ScheduleConstraintError(
            "min_dates_per_program cannot exceed n_windows; "
            f"got {min_dates_per_program} > {n_windows}"
        )
    if not isinstance(block_max_per_day, int) or block_max_per_day <= 0:
        raise ScheduleConstraintError("block_max_per_day must be a positive int")

    out: list[ProgramSpec] = []
    seen_ids: set[str] = set()
    for p in programs:
        if isinstance(p, ProgramSpec):
            spec = p
        elif isinstance(p, dict):
            pid = p.get("id")
            if not isinstance(pid, str) or not pid:
                raise ScheduleConstraintError(f"program id required: {p!r}")
            spec = ProgramSpec(
                id=pid,
                name=str(p.get("name", pid)),
                block=p.get("block"),
            )
        else:
            raise ScheduleConstraintError(
                f"program must be ProgramSpec or dict, got {type(p).__name__}"
            )
        if spec.id in seen_ids:
            raise ScheduleConstraintError(f"duplicate program id: {spec.id}")
        seen_ids.add(spec.id)
        out.append(spec)
    if not out:
        raise ScheduleConstraintError("at least one program is required")
    return out


def _build_windows(year: int, n_windows: int) -> list[list[dt.date]]:
    """Return ``n_windows`` lists of working days that together
    cover the year, roughly equal in size."""
    all_working = list(
        kz_holidays.working_days_in_range(
            dt.date(year, 1, 1), dt.date(year, 12, 31)
        )
    )
    if not all_working:
        return [[] for _ in range(n_windows)]
    # Even split: each window gets ~ len/n_windows days.
    per = len(all_working) / n_windows
    windows: list[list[dt.date]] = []
    for i in range(n_windows):
        start = int(round(i * per))
        end = int(round((i + 1) * per))
        windows.append(all_working[start:end])
    return windows


def distribute_schedule(
    programs: Iterable,
    year: int,
    *,
    min_dates_per_program: int = 3,
    n_windows: int = 6,
    block_max_per_day: int = 3,
    seed: int = 42,
) -> DistributionResult:
    """Place ``min_dates_per_program`` dates for each program across
    ``year``'s working days.

    Algorithm:

    1. Build ``n_windows`` slices of the year's working days.
    2. Shuffle programs deterministically by ``seed``.
    3. For each program, pick one date per window:
       a. Score candidate days by (existing daily load,
          existing same-block load).
       b. Pick the lowest-scoring day; tie-break by date.
       c. Reject if the chosen day would push the same-block
          count over ``block_max_per_day`` — try the next-best.
    4. Programs that couldn't fit a date in some window have
       fewer than ``min_dates_per_program`` outputs; the gap is
       reported in ``unscheduled``.

    The greedy + single-step rejection approach is enough for the
    IBA scale (up to ≈1800 events) — we rely on the year being
    sparsely loaded (≤ 7 events / working day average). A heavier
    CSP (constraint propagation, MAC, etc.) is an over-fit for
    this dataset shape.
    """
    specs = _validate_inputs(
        programs, year, min_dates_per_program, n_windows, block_max_per_day
    )
    windows = _build_windows(year, n_windows)
    if any(not w for w in windows):
        log.warning(
            "schedule solver: empty window(s) for year %s — solver will "
            "return partial result", year,
        )

    rng = random.Random(seed)
    order = specs[:]
    rng.shuffle(order)

    schedule: dict[str, list[str]] = {p.id: [] for p in specs}
    daily_load: dict[str, int] = {}
    daily_block_load: dict[tuple[str, str], int] = {}
    unscheduled: dict[str, int] = {}

    # Pick min_dates_per_program windows evenly spaced across the
    # n_windows split. With min=3, n=6 → indices [0, 2, 4]; with
    # min=4, n=6 → [0, 2, 3, 5]. Even spread is the whole point —
    # taking the first min_dates_per_program windows would cluster
    # every program in the first half of the year.
    chosen_idx = [
        round(i * (n_windows - 1) / (min_dates_per_program - 1)) if min_dates_per_program > 1 else 0
        for i in range(min_dates_per_program)
    ]
    chosen_windows = [windows[i] for i in chosen_idx]

    for spec in order:
        for w_idx, window in enumerate(chosen_windows):
            placed = False
            # Score candidates: lower load = better.
            scored = sorted(
                window,
                key=lambda d, _spec=spec: (
                    daily_load.get(d.isoformat(), 0)
                    + (
                        2 * daily_block_load.get(
                            (d.isoformat(), _spec.block or ""), 0
                        )
                        if _spec.block
                        else 0
                    ),
                    d,
                ),
            )
            for candidate in scored:
                iso = candidate.isoformat()
                # Anti-clustering: respect block cap.
                if spec.block:
                    cur = daily_block_load.get((iso, spec.block), 0)
                    if cur >= block_max_per_day:
                        continue
                # Don't place two dates of same program on same day.
                if iso in schedule[spec.id]:
                    continue
                schedule[spec.id].append(iso)
                daily_load[iso] = daily_load.get(iso, 0) + 1
                if spec.block:
                    key = (iso, spec.block)
                    daily_block_load[key] = daily_block_load.get(key, 0) + 1
                placed = True
                break
            if not placed:
                unscheduled[spec.id] = unscheduled.get(spec.id, 0) + 1

    # Sort each program's date list for deterministic output.
    for pid in schedule:
        schedule[pid].sort()

    return DistributionResult(
        schedule=schedule,
        unscheduled=unscheduled,
        daily_load=daily_load,
    )
