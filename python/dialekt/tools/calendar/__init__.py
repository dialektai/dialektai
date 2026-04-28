"""Calendar utilities for dialekt agents — public holidays, working
days, school terms, etc.

Currently ships:

- :mod:`kz_holidays` — Republic of Kazakhstan public holidays,
  static yearly tables for 2026–2028, used by the schedule
  constraint solver and the program-scheduler agent.
"""

from .kz_holidays import (
    KZ_HOLIDAYS,
    HolidayLookupError,
    get_holidays,
    is_holiday,
    is_working_day,
)

__all__ = [
    "KZ_HOLIDAYS",
    "HolidayLookupError",
    "get_holidays",
    "is_holiday",
    "is_working_day",
]
