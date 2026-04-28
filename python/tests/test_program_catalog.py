"""Tests for ``dialekt.tools.scheduling.catalog``."""
from __future__ import annotations

import json

import pytest

from dialekt.tools.scheduling.catalog import (
    CatalogLoadError,
    load_catalog,
    to_dicts,
)
from dialekt.tools.scheduling.constraint_solver import ProgramSpec


# ---------------------------------------------------------------------------
# YAML
# ---------------------------------------------------------------------------


def test_load_yaml_catalog(tmp_path):
    p = tmp_path / "catalog.yaml"
    p.write_text("""
programs:
  - id: "p1"
    name: "Лидерство"
    block: "leadership"
  - id: "p2"
    name: "Финансы"
    block: "finance"
""", encoding="utf-8")
    progs = load_catalog(p)
    assert len(progs) == 2
    assert progs[0].id == "p1"
    assert progs[0].block == "leadership"
    assert progs[1].name == "Финансы"


def test_load_yaml_strips_whitespace(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text("programs:\n  - id: '  spaced  '\n    name: '  Имя  '\n")
    progs = load_catalog(p)
    assert progs[0].id == "spaced"
    assert progs[0].name == "Имя"


def test_load_yaml_missing_programs_key(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text("not_programs: []")
    with pytest.raises(CatalogLoadError, match="programs"):
        load_catalog(p)


# ---------------------------------------------------------------------------
# JSON
# ---------------------------------------------------------------------------


def test_load_json_array(tmp_path):
    p = tmp_path / "c.json"
    p.write_text(json.dumps([
        {"id": "a", "name": "A", "block": "x"},
        {"id": "b", "name": "B"},
    ]))
    progs = load_catalog(p)
    assert [p.id for p in progs] == ["a", "b"]


def test_load_json_with_programs_key(tmp_path):
    p = tmp_path / "c.json"
    p.write_text(json.dumps({"programs": [{"id": "x", "name": "X"}]}))
    progs = load_catalog(p)
    assert progs[0].id == "x"


def test_load_json_invalid_root(tmp_path):
    p = tmp_path / "c.json"
    p.write_text('"just a string"')
    with pytest.raises(CatalogLoadError):
        load_catalog(p)


# ---------------------------------------------------------------------------
# CSV
# ---------------------------------------------------------------------------


def test_load_csv(tmp_path):
    p = tmp_path / "c.csv"
    p.write_text(
        "id,name,block,duration_days\n"
        "p1,Лидерство,leadership,3\n"
        "p2,Финансы,finance,2\n",
        encoding="utf-8",
    )
    progs = load_catalog(p)
    assert len(progs) == 2
    assert progs[0].name == "Лидерство"
    assert progs[1].block == "finance"


def test_load_csv_no_header(tmp_path):
    p = tmp_path / "c.csv"
    p.write_text("")
    with pytest.raises(CatalogLoadError):
        load_catalog(p)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def test_missing_id_rejected(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text("programs:\n  - name: 'No ID'\n")
    with pytest.raises(CatalogLoadError, match="'id'"):
        load_catalog(p)


def test_missing_name_rejected(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text("programs:\n  - id: 'p1'\n")
    with pytest.raises(CatalogLoadError, match="'name'"):
        load_catalog(p)


def test_duplicate_id_rejected(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text(
        "programs:\n  - id: 'p1'\n    name: 'A'\n  - id: 'p1'\n    name: 'B'\n"
    )
    with pytest.raises(CatalogLoadError, match="duplicate"):
        load_catalog(p)


def test_empty_catalog_rejected(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text("programs: []\n")
    with pytest.raises(CatalogLoadError, match="empty"):
        load_catalog(p)


def test_unsupported_format_rejected(tmp_path):
    p = tmp_path / "c.txt"
    p.write_text("anything")
    with pytest.raises(CatalogLoadError, match="unsupported"):
        load_catalog(p)


def test_missing_file_rejected(tmp_path):
    with pytest.raises(CatalogLoadError, match="not found"):
        load_catalog(tmp_path / "nope.yaml")


# ---------------------------------------------------------------------------
# to_dicts round-trip
# ---------------------------------------------------------------------------


def test_to_dicts_round_trip():
    progs = [ProgramSpec("a", "Alpha", "x"), ProgramSpec("b", "Beta", None)]
    dicts = to_dicts(progs)
    assert dicts == [
        {"id": "a", "name": "Alpha", "block": "x"},
        {"id": "b", "name": "Beta", "block": None},
    ]


# ---------------------------------------------------------------------------
# Solver integration
# ---------------------------------------------------------------------------


def test_loaded_catalog_feeds_solver(tmp_path):
    """Smoke test: load YAML → to_dicts → distribute_schedule."""
    from dialekt.tools.scheduling import distribute_schedule

    p = tmp_path / "c.yaml"
    p.write_text(
        "programs:\n"
        "  - id: a\n    name: A\n    block: alpha\n"
        "  - id: b\n    name: B\n    block: alpha\n"
        "  - id: c\n    name: C\n    block: beta\n",
        encoding="utf-8",
    )
    progs = load_catalog(p)
    result = distribute_schedule(to_dicts(progs), 2026)
    assert result.fully_scheduled
    assert set(result.schedule.keys()) == {"a", "b", "c"}


def test_example_catalog_file_loads():
    """The example catalog shipped under agents/iba/ must parse."""
    from pathlib import Path

    example = (
        Path(__file__).parents[2] / "agents" / "iba" / "example_catalog.yaml"
    )
    assert example.exists(), f"example catalog missing at {example}"
    progs = load_catalog(example)
    assert len(progs) >= 3
