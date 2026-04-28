"""Republic of Kazakhstan public-holiday calendar.

Static yearly tables for 2026–2028 — the years the IBA pilot
realistically schedules. Sourced from:

- adilet.zan.kz — Закон РК "О праздниках в Республике Казахстан"
  (national holidays + Constitution Day + Independence Day shifts)
- Government Decree on Курбан Ait (movable, declared annually by
  the Ministry of Culture). Dates below are confirmed by published
  decrees as of 2026-04-28; verify the next year's value before
  rolling the table forward.

The schedule constraint solver consumes ``get_holidays(year)`` to
reject candidate dates falling on national holidays or government-
declared transferred-rest days. Replace the static table with an
adilet RSS-driven loader once that integration lands.

Important: when the government shifts a holiday onto an adjacent
weekend (e.g. Saturday becomes a working day to compensate for a
Monday holiday), the moved working day appears in
``WORKING_DAYS_OVERRIDE``. ``is_working_day`` checks both lists.
"""
from __future__ import annotations

import datetime as dt
from typing import Iterable


class HolidayLookupError(LookupError):
    """Raised when a year is requested outside the curated table."""


# Each entry: (ISO date, name).
# Курбан Ait is movable; the dates below match published government
# decrees. ALWAYS re-verify before extending into a new year.
_HOLIDAYS_BY_YEAR: dict[int, list[tuple[str, str]]] = {
    2026: [
        ("2026-01-01", "Новый год"),
        ("2026-01-02", "Новый год"),
        ("2026-01-07", "Православное Рождество"),
        ("2026-03-08", "Международный женский день"),
        ("2026-03-21", "Наурыз мейрамы"),
        ("2026-03-22", "Наурыз мейрамы"),
        ("2026-03-23", "Наурыз мейрамы"),
        ("2026-05-01", "Праздник единства народа Казахстана"),
        ("2026-05-07", "День защитника Отечества"),
        ("2026-05-09", "День Победы"),
        ("2026-05-27", "Курбан Ait"),  # 1-day movable; confirm annually
        ("2026-07-06", "День столицы"),
        ("2026-08-30", "День Конституции"),
        ("2026-12-16", "День Независимости"),
    ],
    2027: [
        ("2027-01-01", "Новый год"),
        ("2027-01-02", "Новый год"),
        ("2027-01-07", "Православное Рождество"),
        ("2027-03-08", "Международный женский день"),
        ("2027-03-21", "Наурыз мейрамы"),
        ("2027-03-22", "Наурыз мейрамы"),
        ("2027-03-23", "Наурыз мейрамы"),
        ("2027-05-01", "Праздник единства народа Казахстана"),
        ("2027-05-07", "День защитника Отечества"),
        ("2027-05-09", "День Победы"),
        ("2027-05-17", "Курбан Ait"),  # estimate; verify before use
        ("2027-07-06", "День столицы"),
        ("2027-08-30", "День Конституции"),
        ("2027-12-16", "День Независимости"),
    ],
    2028: [
        ("2028-01-01", "Новый год"),
        ("2028-01-02", "Новый год"),
        ("2028-01-07", "Православное Рождество"),
        ("2028-03-08", "Международный женский день"),
        ("2028-03-21", "Наурыз мейрамы"),
        ("2028-03-22", "Наурыз мейрамы"),
        ("2028-03-23", "Наурыз мейрамы"),
        ("2028-05-01", "Праздник единства народа Казахстана"),
        ("2028-05-07", "День защитника Отечества"),
        ("2028-05-09", "День Победы"),
        ("2028-05-06", "Курбан Ait"),  # estimate; verify before use
        ("2028-07-06", "День столицы"),
        ("2028-08-30", "День Конституции"),
        ("2028-12-16", "День Независимости"),
    ],
}


# Government-declared compensation: moves a normally-weekend day
# into the working calendar (e.g. a Saturday becomes a working day
# when a Friday holiday is followed by a Monday transfer-of-rest).
# Empty by default — populate when the government decree publishes.
WORKING_DAYS_OVERRIDE: dict[int, list[str]] = {
    2026: [],
    2027: [],
    2028: [],
}


# Days normally considered working that were declared rest by
# decree (transfer-of-rest from the next-week holiday). Adds to the
# weekend block.
ADDITIONAL_REST_DAYS: dict[int, list[str]] = {
    2026: [],
    2027: [],
    2028: [],
}


# Snapshot used by tests to round-trip the dataset shape.
KZ_HOLIDAYS = {
    year: [{"date": d, "name": n} for d, n in entries]
    for year, entries in _HOLIDAYS_BY_YEAR.items()
}


def get_holidays(year: int) -> list[dict]:
    """Return the curated holiday list for ``year``.

    Raises :class:`HolidayLookupError` for years outside the table.
    Each item is ``{"date": "YYYY-MM-DD", "name": "..."}``.
    """
    if year not in _HOLIDAYS_BY_YEAR:
        supported = sorted(_HOLIDAYS_BY_YEAR.keys())
        raise HolidayLookupError(
            f"no curated holiday table for {year}; supported: {supported}"
        )
    return [{"date": d, "name": n} for d, n in _HOLIDAYS_BY_YEAR[year]]


def _holiday_dates(year: int) -> set[str]:
    return {d for d, _ in _HOLIDAYS_BY_YEAR.get(year, [])} | set(
        ADDITIONAL_REST_DAYS.get(year, [])
    )


def _override_working_days(year: int) -> set[str]:
    return set(WORKING_DAYS_OVERRIDE.get(year, []))


def _coerce_date(value) -> dt.date:
    if isinstance(value, dt.date):
        return value
    if isinstance(value, str):
        return dt.date.fromisoformat(value)
    raise TypeError(f"expected date or ISO string, got {type(value).__name__}")


def is_holiday(value) -> bool:
    """True when ``value`` (date or ISO string) is a curated holiday
    or government-declared rest day."""
    d = _coerce_date(value)
    return d.isoformat() in _holiday_dates(d.year)


def is_working_day(value) -> bool:
    """True when ``value`` is a working day:
    - weekday (Mon-Fri) AND not in the holiday list, OR
    - weekend day explicitly declared a working day by decree.

    This is the predicate the schedule solver uses to filter
    candidate dates.
    """
    d = _coerce_date(value)
    iso = d.isoformat()
    if iso in _override_working_days(d.year):
        return True
    if d.weekday() >= 5:  # Saturday=5, Sunday=6
        return False
    return iso not in _holiday_dates(d.year)


def working_days_in_range(
    start: dt.date | str,
    end: dt.date | str,
) -> Iterable[dt.date]:
    """Yield every working day in [start, end] inclusive, ordered."""
    s = _coerce_date(start)
    e = _coerce_date(end)
    if e < s:
        return
    cur = s
    one = dt.timedelta(days=1)
    while cur <= e:
        if is_working_day(cur):
            yield cur
        cur += one
