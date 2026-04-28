"""Tests for the schedule constraint solver + its MCP tool."""
from __future__ import annotations

import datetime as dt

import pytest

from dialekt.mcp.server import MCPServer, ServerConfig
from dialekt.mcp.server.config import ApiKey
from dialekt.mcp.server.tools._wrap import ToolAccessDenied
from dialekt.mcp.server.tools.scheduling import register_scheduling_tools
from dialekt.tools.calendar import kz_holidays
from dialekt.tools.scheduling.constraint_solver import (
    DistributionResult,
    ProgramSpec,
    ScheduleConstraintError,
    distribute_schedule,
)


def _spec(pid, block=None):
    return {"id": pid, "name": pid, "block": block}


# ---------------------------------------------------------------------------
# input validation
# ---------------------------------------------------------------------------


def test_empty_programs_rejected():
    with pytest.raises(ScheduleConstraintError, match="at least one program"):
        distribute_schedule([], 2026)


def test_year_out_of_range_rejected():
    with pytest.raises(ScheduleConstraintError, match="year"):
        distribute_schedule([_spec("p1")], 2099)


def test_duplicate_ids_rejected():
    with pytest.raises(ScheduleConstraintError, match="duplicate"):
        distribute_schedule(
            [_spec("p1"), _spec("p1")],
            2026,
        )


def test_min_dates_exceeds_windows_rejected():
    with pytest.raises(ScheduleConstraintError):
        distribute_schedule(
            [_spec("p1")],
            2026,
            min_dates_per_program=10,
            n_windows=3,
        )


# ---------------------------------------------------------------------------
# happy paths
# ---------------------------------------------------------------------------


def test_single_program_three_dates():
    result = distribute_schedule([_spec("p1")], 2026)
    assert result.fully_scheduled
    dates = result.schedule["p1"]
    assert len(dates) == 3
    # Each is a working day
    for iso in dates:
        d = dt.date.fromisoformat(iso)
        assert kz_holidays.is_working_day(d), f"{iso} is not a working day"
    # In year
    for iso in dates:
        assert iso.startswith("2026")
    # Sorted
    assert dates == sorted(dates)


def test_dates_distributed_across_year():
    """Three dates from a 6-window split should land in distinct
    parts of the year — not all in January."""
    result = distribute_schedule([_spec("p1")], 2026)
    dates = [dt.date.fromisoformat(d) for d in result.schedule["p1"]]
    # No two dates within the same month
    months = {(d.year, d.month) for d in dates}
    assert len(months) == 3, f"dates clustered into months: {months}"
    # Spread across year — first date in H1, last in H2
    assert dates[0].month <= 6
    assert dates[-1].month >= 6


def test_block_anti_clustering():
    """If 5 programs share a block and block_max_per_day=2, no day
    should host more than 2 programs from that block."""
    progs = [_spec(f"p{i}", block="finance") for i in range(5)]
    result = distribute_schedule(progs, 2026, block_max_per_day=2)
    # Build a (date, count) view limited to 'finance' programs
    by_day: dict[str, int] = {}
    for pid, dates in result.schedule.items():
        for d in dates:
            by_day[d] = by_day.get(d, 0) + 1
    # Cap honoured
    assert all(c <= 2 for c in by_day.values()), by_day


def test_no_two_dates_of_same_program_share_a_day():
    progs = [_spec("p1")]
    result = distribute_schedule(progs, 2026)
    dates = result.schedule["p1"]
    assert len(set(dates)) == len(dates)


def test_all_dates_are_weekdays():
    progs = [_spec(f"p{i}") for i in range(20)]
    result = distribute_schedule(progs, 2026)
    for pid, dates in result.schedule.items():
        for iso in dates:
            d = dt.date.fromisoformat(iso)
            assert d.weekday() < 5, f"{iso} for {pid} is a weekend"


def test_no_dates_on_kz_holidays():
    progs = [_spec(f"p{i}") for i in range(20)]
    result = distribute_schedule(progs, 2026)
    for pid, dates in result.schedule.items():
        for iso in dates:
            assert not kz_holidays.is_holiday(iso), f"{iso} is a KZ holiday"


# ---------------------------------------------------------------------------
# determinism
# ---------------------------------------------------------------------------


def test_same_seed_same_result():
    progs = [_spec(f"p{i}") for i in range(10)]
    a = distribute_schedule(progs, 2026, seed=42)
    b = distribute_schedule(progs, 2026, seed=42)
    assert a.schedule == b.schedule


def test_different_seed_different_assignment():
    progs = [_spec(f"p{i}") for i in range(10)]
    a = distribute_schedule(progs, 2026, seed=42)
    b = distribute_schedule(progs, 2026, seed=999)
    # Not strictly guaranteed they differ for tiny inputs, but for
    # 10 programs across 6 windows the order of placement should
    # produce different assignments on at least one program.
    assert a.schedule != b.schedule


# ---------------------------------------------------------------------------
# scale stress test (300 programs × 3 dates)
# ---------------------------------------------------------------------------


def test_scale_300_programs():
    """IBA-shaped problem: 300 programs across ~250 working days
    with no block clustering. Should fully schedule."""
    progs = [_spec(f"p{i:03d}", block=f"block_{i % 30}") for i in range(300)]
    result = distribute_schedule(progs, 2026, block_max_per_day=3)
    # Allow small unscheduled tail — not every block will fit cleanly.
    # Acceptance: at least 95% of programs got all 3 dates.
    full = sum(1 for d in result.schedule.values() if len(d) == 3)
    assert full / len(progs) >= 0.95, f"only {full}/300 fully scheduled"


# ---------------------------------------------------------------------------
# DistributionResult shape
# ---------------------------------------------------------------------------


def test_to_dict_round_trip():
    result = distribute_schedule([_spec("p1")], 2026)
    d = result.to_dict()
    assert "schedule" in d
    assert "unscheduled" in d
    assert "daily_load" in d
    assert d["fully_scheduled"] is True
    assert d["schedule"]["p1"] == result.schedule["p1"]


# ---------------------------------------------------------------------------
# MCP tool
# ---------------------------------------------------------------------------


def _build_server():
    events: list[dict] = []
    srv = MCPServer(
        ServerConfig(),
        audit_callback=lambda **p: events.append(p),
    )
    srv.bind_active_key(ApiKey(id="test", value="x" * 32))
    register_scheduling_tools(srv)
    return srv, events


def test_distribute_schedule_tool_happy_path():
    srv, _ = _build_server()
    tool = srv.fastmcp._tool_manager._tools["dialekt_distribute_schedule"].fn
    out = tool(
        programs=[{"id": "leadership", "name": "Leadership"}],
        year=2026,
    )
    assert out["fully_scheduled"] is True
    assert len(out["schedule"]["leadership"]) == 3


def test_distribute_schedule_tool_invalid_input():
    srv, _ = _build_server()
    tool = srv.fastmcp._tool_manager._tools["dialekt_distribute_schedule"].fn
    out = tool(programs=[], year=2026)
    assert out["error"] is True
    assert out["reason"] == "invalid_input"


def test_distribute_schedule_tool_audit_records_size():
    srv, events = _build_server()
    tool = srv.fastmcp._tool_manager._tools["dialekt_distribute_schedule"].fn
    tool(
        programs=[{"id": "a"}, {"id": "b"}, {"id": "c"}],
        year=2026,
    )
    success = [e for e in events if e.get("result") == "success"]
    assert success
    extra = success[-1]["extra"]
    assert extra["n_programs"] == 3
    assert extra["year"] == 2026


def test_scheduling_category_disabled_refuses():
    events: list[dict] = []
    srv = MCPServer(
        ServerConfig(enabled_categories=["database"]),
        audit_callback=lambda **p: events.append(p),
    )
    srv.bind_active_key(ApiKey(id="test", value="x" * 32))
    register_scheduling_tools(srv)
    tool = srv.fastmcp._tool_manager._tools["dialekt_distribute_schedule"].fn
    with pytest.raises(ToolAccessDenied):
        tool(programs=[{"id": "p"}], year=2026)
    denied = [e for e in events if e.get("result") == "permission_denied"]
    assert len(denied) == 1
