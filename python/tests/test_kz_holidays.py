"""Tests for ``dialekt.tools.calendar.kz_holidays`` and the
``dialekt_kz_holidays`` MCP tool."""
from __future__ import annotations

import datetime as dt

import pytest

from dialekt.mcp.server import MCPServer, ServerConfig
from dialekt.mcp.server.config import ApiKey
from dialekt.mcp.server.tools._wrap import ToolAccessDenied
from dialekt.mcp.server.tools.calendar import register_calendar_tools
from dialekt.tools.calendar import kz_holidays


# ---------------------------------------------------------------------------
# get_holidays / table shape
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("year", [2026, 2027, 2028])
def test_get_holidays_returns_curated_table(year):
    holidays = kz_holidays.get_holidays(year)
    assert holidays
    for h in holidays:
        assert "date" in h
        assert "name" in h
        # ISO format
        dt.date.fromisoformat(h["date"])
        # within the requested year
        assert h["date"].startswith(str(year))


def test_get_holidays_unknown_year_raises():
    with pytest.raises(kz_holidays.HolidayLookupError):
        kz_holidays.get_holidays(2099)


def test_kz_holidays_dict_shape():
    """The KZ_HOLIDAYS exported dict mirrors get_holidays for each
    curated year — keep them in sync if the table moves."""
    for year, items in kz_holidays.KZ_HOLIDAYS.items():
        assert items == kz_holidays.get_holidays(year)


# ---------------------------------------------------------------------------
# is_holiday / is_working_day
# ---------------------------------------------------------------------------


def test_is_holiday_known_dates():
    assert kz_holidays.is_holiday("2026-01-01") is True
    assert kz_holidays.is_holiday("2026-03-22") is True   # Наурыз
    assert kz_holidays.is_holiday("2026-12-16") is True   # День Независимости


def test_is_holiday_random_workday():
    assert kz_holidays.is_holiday("2026-02-17") is False  # Tuesday Feb 17


def test_is_holiday_accepts_date_object():
    assert kz_holidays.is_holiday(dt.date(2026, 1, 7)) is True  # Православное Рождество


def test_is_working_day_weekday_non_holiday():
    # 2026-04-28 = Tuesday
    assert kz_holidays.is_working_day("2026-04-28") is True


def test_is_working_day_weekend():
    # 2026-04-25 = Saturday
    assert kz_holidays.is_working_day("2026-04-25") is False


def test_is_working_day_holiday_on_weekday():
    # 2026-08-30 = День Конституции (Sunday in 2026, but still holiday)
    # Pick weekday holiday: 2026-05-09 = Saturday (Victory Day) — weekend AND holiday
    # Pick a true weekday holiday: 2026-01-01 (Thursday)
    assert kz_holidays.is_working_day("2026-01-01") is False


def test_working_days_in_range_skips_weekends_and_holidays():
    days = list(
        kz_holidays.working_days_in_range("2026-01-01", "2026-01-12")
    )
    iso = [d.isoformat() for d in days]
    # 1, 2 (holiday), 7 (Christmas) excluded; weekends 3-4, 10-11 excluded
    assert "2026-01-01" not in iso
    assert "2026-01-02" not in iso
    assert "2026-01-07" not in iso
    assert "2026-01-03" not in iso
    assert "2026-01-04" not in iso
    assert "2026-01-10" not in iso
    assert "2026-01-11" not in iso
    # Working days remain
    assert "2026-01-05" in iso  # Monday
    assert "2026-01-06" in iso  # Tuesday
    assert "2026-01-08" in iso  # Thursday
    assert "2026-01-09" in iso  # Friday
    assert "2026-01-12" in iso  # Monday


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
    register_calendar_tools(srv)
    return srv, events


def test_kz_holidays_tool_returns_year():
    srv, _ = _build_server()
    tool = srv.fastmcp._tool_manager._tools["dialekt_kz_holidays"].fn
    out = tool(year=2026)
    assert out["year"] == 2026
    assert any(h["date"] == "2026-03-22" for h in out["holidays"])
    assert isinstance(out["additional_rest"], list)
    assert isinstance(out["working_overrides"], list)


def test_kz_holidays_tool_unknown_year():
    srv, _ = _build_server()
    tool = srv.fastmcp._tool_manager._tools["dialekt_kz_holidays"].fn
    out = tool(year=2099)
    assert out["error"] is True
    assert out["reason"] == "year_not_curated"


def test_kz_holidays_tool_invalid_year_string():
    srv, _ = _build_server()
    tool = srv.fastmcp._tool_manager._tools["dialekt_kz_holidays"].fn
    out = tool(year="not-a-year")
    assert out["error"] is True
    assert out["reason"] == "invalid_year"


def test_kz_holidays_tool_audit():
    srv, events = _build_server()
    tool = srv.fastmcp._tool_manager._tools["dialekt_kz_holidays"].fn
    tool(year=2026)
    success = [e for e in events if e.get("result") == "success"]
    assert success and success[-1]["action"] == "dialekt_kz_holidays"


def test_calendar_category_disabled_refuses():
    events: list[dict] = []
    srv = MCPServer(
        ServerConfig(enabled_categories=["database"]),
        audit_callback=lambda **p: events.append(p),
    )
    srv.bind_active_key(ApiKey(id="test", value="x" * 32))
    register_calendar_tools(srv)
    tool = srv.fastmcp._tool_manager._tools["dialekt_kz_holidays"].fn
    with pytest.raises(ToolAccessDenied):
        tool(year=2026)
    denied = [e for e in events if e.get("result") == "permission_denied"]
    assert len(denied) == 1
