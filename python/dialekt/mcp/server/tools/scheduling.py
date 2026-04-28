"""Schedule constraint-solver tool for the MCP server.

Single tool — ``dialekt_distribute_schedule`` — wraps the
:func:`dialekt.tools.scheduling.constraint_solver.distribute_schedule`
solver so the program_scheduler agent can place 300+ programs ×
3 dates × 2 formats per year without rolling its own backtracking
in a Python sandbox cell.
"""
from __future__ import annotations

from typing import Any, Optional, TYPE_CHECKING

from dialekt.mcp.server.tools._wrap import call_tool_wrapped
from dialekt.tools.scheduling.constraint_solver import (
    ScheduleConstraintError,
    distribute_schedule,
)

if TYPE_CHECKING:
    from dialekt.mcp.server.server import MCPServer


def register_scheduling_tools(server: "MCPServer") -> list[str]:
    """Attach the schedule-distribution tool. Returns names."""
    registered: list[str] = []

    @server.fastmcp.tool(
        description=(
            "Distribute N programs × K dates each across a year of "
            "working days, honouring KZ holidays + per-block "
            "anti-clustering. ``programs`` is a list of "
            "``{id, name, block?}``. Returns "
            "``{schedule: {program_id: [dates...]}, "
            "unscheduled: {program_id: gaps}, daily_load: "
            "{date: count}, fully_scheduled: bool}``. "
            "``min_dates_per_program`` (default 3) and ``n_windows`` "
            "(default 6) drive the per-program quota and yearly "
            "split. ``block_max_per_day`` (default 3) caps how many "
            "programs from one block can share a single date. "
            "``seed`` (default 42) makes the output deterministic."
        )
    )
    def dialekt_distribute_schedule(
        programs: list[dict[str, Any]],
        year: int,
        min_dates_per_program: int = 3,
        n_windows: int = 6,
        block_max_per_day: int = 3,
        seed: int = 42,
    ) -> dict:
        def _handler() -> dict:
            try:
                result = distribute_schedule(
                    programs,
                    year,
                    min_dates_per_program=min_dates_per_program,
                    n_windows=n_windows,
                    block_max_per_day=block_max_per_day,
                    seed=seed,
                )
            except ScheduleConstraintError as e:
                return {
                    "error": True,
                    "reason": "invalid_input",
                    "detail": str(e),
                }
            return result.to_dict()

        return call_tool_wrapped(
            server,
            "dialekt_distribute_schedule",
            _handler,
            extra_audit={
                "year": year,
                "n_programs": len(programs) if isinstance(programs, list) else None,
                "min_dates_per_program": min_dates_per_program,
            },
        )

    registered.append("dialekt_distribute_schedule")
    return registered
