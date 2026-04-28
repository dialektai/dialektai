"""KZ calendar tool for the MCP server.

Single tool — ``dialekt_kz_holidays`` — that exposes the curated
public-holiday table from :mod:`dialekt.tools.calendar.kz_holidays`
to agents (specifically program_scheduler.yaml). Returns the
dataset for one year so the LLM doesn't need to parse a Python
list — and so the schedule solver can be run from inside the
agent's Python sandbox without bundling holiday data twice.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from dialekt.mcp.server.tools._wrap import call_tool_wrapped
from dialekt.tools.calendar import kz_holidays

if TYPE_CHECKING:
    from dialekt.mcp.server.server import MCPServer


def register_calendar_tools(server: "MCPServer") -> list[str]:
    """Attach the KZ holiday tool. Returns registered names."""
    registered: list[str] = []

    @server.fastmcp.tool(
        description=(
            "Return the Republic of Kazakhstan public holidays for a "
            "given year, plus any government-declared transfer-of-rest "
            "overrides. Output: ``{year, holidays: [{date, name}], "
            "additional_rest: [...], working_overrides: [...]}``. "
            "Curated table covers 2026–2028; requesting another year "
            "raises an error so the caller can refresh the table."
        )
    )
    def dialekt_kz_holidays(year: int) -> dict:
        def _handler() -> dict:
            try:
                holidays = kz_holidays.get_holidays(int(year))
            except (TypeError, ValueError):
                return {
                    "error": True,
                    "reason": "invalid_year",
                    "detail": f"year must be int, got {year!r}",
                }
            except kz_holidays.HolidayLookupError as e:
                return {
                    "error": True,
                    "reason": "year_not_curated",
                    "detail": str(e),
                }
            return {
                "year": int(year),
                "holidays": holidays,
                "additional_rest": list(
                    kz_holidays.ADDITIONAL_REST_DAYS.get(int(year), [])
                ),
                "working_overrides": list(
                    kz_holidays.WORKING_DAYS_OVERRIDE.get(int(year), [])
                ),
            }

        return call_tool_wrapped(
            server,
            "dialekt_kz_holidays",
            _handler,
            extra_audit={"year": year},
        )

    registered.append("dialekt_kz_holidays")
    return registered
