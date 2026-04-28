"""Program-catalog import for IBA-style scheduling.

The program_scheduler agent doesn't paste 300 program names into
the prompt — it loads them from a catalog file in the agent's
workspace. This module is the loader: tolerates YAML, JSON, or
CSV; emits a list of :class:`ProgramSpec` ready for the
constraint solver.

Expected schema (YAML/JSON):

    programs:
      - id: "leadership-1"
        name: "Стратегическое лидерство"
        block: "leadership"
        duration_days: 3
      - id: "finance-tax-1"
        name: "Налоговое планирование 2026"
        block: "finance"
        ...

CSV equivalent:

    id,name,block,duration_days
    leadership-1,Стратегическое лидерство,leadership,3
    finance-tax-1,Налоговое планирование 2026,finance,2

Only ``id`` and ``name`` are required. ``block`` is optional but
strongly recommended — without it the constraint solver can't run
its anti-clustering check.

The loader lives outside the MCP boundary (it's a library function
the program_scheduler agent imports through Open Interpreter's
Python sandbox or the operator runs ahead of time). No MCP tool
wrapper today; if a future agent wants to load catalogs at runtime
through MCP, add ``catalog`` as a category and wrap it.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

import yaml as _yaml

from .constraint_solver import ProgramSpec


class CatalogLoadError(ValueError):
    """Raised on malformed catalog input."""


REQUIRED_FIELDS = ("id", "name")
OPTIONAL_FIELDS = ("block", "duration_days", "format", "category", "description")


def _coerce_program(row: dict, line_no: int | None = None) -> ProgramSpec:
    if not isinstance(row, dict):
        raise CatalogLoadError(
            f"row {line_no}: expected dict, got {type(row).__name__}"
        )
    pid = row.get("id")
    name = row.get("name")
    if not isinstance(pid, str) or not pid.strip():
        raise CatalogLoadError(f"row {line_no}: missing required field 'id'")
    if not isinstance(name, str) or not name.strip():
        raise CatalogLoadError(f"row {line_no}: missing required field 'name'")
    block = row.get("block")
    if block is not None and not isinstance(block, str):
        block = str(block)
    return ProgramSpec(id=pid.strip(), name=name.strip(), block=block)


def load_catalog(path: str | Path) -> list[ProgramSpec]:
    """Read a YAML / JSON / CSV catalog and return ProgramSpec list.

    Format detected by suffix. The function is tolerant of
    surrounding whitespace, BOM, and comments inside YAML/JSON.
    Duplicates raise :class:`CatalogLoadError`.
    """
    p = Path(path).expanduser()
    if not p.exists():
        raise CatalogLoadError(f"catalog file not found: {p}")
    suffix = p.suffix.lower()

    rows: list[dict[str, Any]]
    if suffix in (".yaml", ".yml"):
        try:
            data = _yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        except _yaml.YAMLError as e:
            raise CatalogLoadError(f"YAML parse error: {e}") from e
        if not isinstance(data, dict):
            raise CatalogLoadError(
                "YAML root must be a mapping with a 'programs' key"
            )
        items = data.get("programs")
        if not isinstance(items, list):
            raise CatalogLoadError("YAML missing 'programs' list")
        rows = [r for r in items if isinstance(r, dict)]
    elif suffix == ".json":
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            raise CatalogLoadError(f"JSON parse error: {e}") from e
        if isinstance(data, list):
            rows = [r for r in data if isinstance(r, dict)]
        elif isinstance(data, dict):
            items = data.get("programs")
            if not isinstance(items, list):
                raise CatalogLoadError(
                    "JSON object must contain 'programs' list"
                )
            rows = [r for r in items if isinstance(r, dict)]
        else:
            raise CatalogLoadError(
                "JSON root must be a list of programs or {programs: [...]}"
            )
    elif suffix == ".csv":
        rows = []
        with p.open(encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            if not reader.fieldnames:
                raise CatalogLoadError("CSV has no header row")
            for row_no, row in enumerate(reader, start=2):
                rows.append(row)
    else:
        raise CatalogLoadError(
            f"unsupported catalog format: {suffix!r} "
            "(use .yaml / .yml / .json / .csv)"
        )

    out: list[ProgramSpec] = []
    seen_ids: set[str] = set()
    for i, row in enumerate(rows, start=1):
        spec = _coerce_program(row, line_no=i)
        if spec.id in seen_ids:
            raise CatalogLoadError(f"duplicate program id: {spec.id!r}")
        seen_ids.add(spec.id)
        out.append(spec)

    if not out:
        raise CatalogLoadError("catalog is empty — no programs found")
    return out


def to_dicts(programs: list[ProgramSpec]) -> list[dict]:
    """Convert ProgramSpec list back to plain dicts — useful when
    handing the catalog into ``dialekt_distribute_schedule`` from
    the agent's Python sandbox."""
    return [
        {"id": p.id, "name": p.name, "block": p.block}
        for p in programs
    ]
