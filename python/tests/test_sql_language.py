"""Tests for the DialektSQL Open Interpreter language handler.

After the PluginContext refactor (2026-04-24) DialektSQL dispatches
through `get_context()` rather than calling httpx directly. These tests
inject a `_FakePluginContext` via `set_context()` to capture the request
and shape the response.
"""
from unittest.mock import MagicMock

import pytest

from dialekt.llm.sql_language import DialektSQL, _format_result, _prefix_for
from dialekt.llm import _plugin_context as _pc


class _FakeInterpreter:
    def __init__(self, conn_id=None, driver=None):
        self._dialekt_sql_conn = conn_id
        self._dialekt_sql_driver = driver


class _FakeComputer:
    def __init__(self, conn_id=None, driver=None):
        self.interpreter = _FakeInterpreter(conn_id, driver)


class _FakePluginContext:
    """Stand-in that records post() calls and returns a preset response."""

    def __init__(self, response=None, raise_on_post=None):
        self.response = response
        self.raise_on_post = raise_on_post
        self.calls: list[dict] = []

    def post(self, path, **kwargs):
        self.calls.append({"path": path, **kwargs})
        if self.raise_on_post is not None:
            raise self.raise_on_post
        return self.response

    def close(self):
        pass

    @property
    def last_path(self) -> str:
        return self.calls[-1]["path"] if self.calls else ""


@pytest.fixture
def restore_context():
    """Restore the default PluginContext after each test so injections
    don't leak between cases.
    """
    original = _pc.get_context()
    yield
    _pc.set_context(original)


def test_format_result_renders_markdown_table():
    data = {
        "columns": ["id", "name"],
        "rows": [[1, "Alice"], [2, "Bob"]],
        "row_count": 2,
        "truncated": False,
    }
    out = _format_result(data)
    assert "| id | name |" in out
    assert "| 1 | Alice |" in out
    assert "| 2 | Bob |" in out
    assert "row_count=2" in out


def test_format_result_includes_truncation_notice():
    data = {"columns": ["id"], "rows": [[i] for i in range(10)], "row_count": 500, "truncated": True}
    out = _format_result(data)
    assert "(truncated by row_limit)" in out
    assert "row_count=500" in out


def test_format_result_caps_displayed_rows():
    rows = [[i] for i in range(200)]
    data = {"columns": ["id"], "rows": rows, "row_count": 200}
    out = _format_result(data)
    assert "150 more rows not shown" in out  # 200 - 50 cap


def test_format_result_zero_rows():
    data = {"columns": ["id", "name"], "rows": [], "row_count": 0}
    out = _format_result(data)
    assert "(0 rows)" in out
    assert "row_count=0" in out


def test_format_result_includes_warning():
    data = {"columns": ["n"], "rows": [[1]], "row_count": 1, "warning": "soft limit reached"}
    out = _format_result(data)
    assert "⚠ soft limit reached" in out


def test_format_result_handles_none_cells():
    data = {"columns": ["a", "b"], "rows": [[1, None]], "row_count": 1}
    out = _format_result(data)
    # None renders as empty string, not "None"
    assert "| 1 |  |" in out


def test_run_without_binding_reports_error():
    handler = DialektSQL(_FakeComputer(conn_id=None))
    chunks = list(handler.run("SELECT 1"))
    assert len(chunks) == 1
    assert "No database connection" in chunks[0]["content"]
    assert chunks[0]["type"] == "console"


def test_run_with_binding_calls_backend_and_formats_output(restore_context):
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {
        "columns": ["count"],
        "rows": [[42]],
        "row_count": 1,
    }
    ctx = _FakePluginContext(response=resp)
    _pc.set_context(ctx)

    handler = DialektSQL(_FakeComputer(conn_id="conn-123"))
    chunks = list(handler.run("SELECT COUNT(*) FROM orders"))

    assert len(ctx.calls) == 1, "plugin must hit the backend exactly once"
    assert ctx.last_path == "/connections/conn-123/query"
    # retry:false avoids triggering the server-side recursive validate loop.
    assert ctx.calls[0]["json"] == {"sql": "SELECT COUNT(*) FROM orders", "retry": False}
    assert len(chunks) == 1
    content = chunks[0]["content"]
    assert "42" in content
    assert "count" in content


def test_run_with_backend_4xx_surfaces_error(restore_context):
    resp = MagicMock()
    resp.status_code = 400
    resp.text = "syntax error at or near FROMM"
    _pc.set_context(_FakePluginContext(response=resp))

    handler = DialektSQL(_FakeComputer(conn_id="conn-123"))
    chunks = list(handler.run("SELECT * FROMM orders"))

    assert len(chunks) == 1
    assert "SQL error (400)" in chunks[0]["content"]
    assert "syntax error" in chunks[0]["content"]


def test_run_with_transport_error_surfaces_it(restore_context):
    import httpx

    _pc.set_context(_FakePluginContext(
        raise_on_post=httpx.ConnectError("could not reach backend"),
    ))

    handler = DialektSQL(_FakeComputer(conn_id="conn-123"))
    chunks = list(handler.run("SELECT 1"))

    assert len(chunks) == 1
    assert "SQL transport error" in chunks[0]["content"]


# ── _prefix_for: driver → router prefix routing ──────────────────────────────


@pytest.mark.parametrize("driver,expected", [
    (None,         "/connections"),
    ("",           "/connections"),
    ("postgres",   "/connections"),
    ("postgresql", "/connections"),
    ("pg",         "/connections"),
    ("POSTGRES",   "/connections"),  # case-insensitive
    ("mysql",      "/mysql-connections"),
    ("MySQL",      "/mysql-connections"),
    ("clickhouse", "/ch-connections"),
    ("ch",         "/ch-connections"),
    ("unknown",    "/connections"),  # graceful fallback
])
def test_prefix_for_driver_routes_to_correct_backend(driver, expected):
    assert _prefix_for(driver) == expected


def test_run_with_mysql_driver_hits_mysql_connections_prefix(restore_context):
    """Regression: before this fix DialektSQL always POSTed to
    /connections/{id}/query, so mysql conn_ids got a 400 from the
    postgres router. Now it must route via /mysql-connections.
    """
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"columns": ["n"], "rows": [[4]], "row_count": 1}
    ctx = _FakePluginContext(response=resp)
    _pc.set_context(ctx)

    handler = DialektSQL(_FakeComputer(conn_id="mysql-xyz", driver="mysql"))
    list(handler.run("SELECT COUNT(*) FROM orders"))

    assert ctx.last_path == "/mysql-connections/mysql-xyz/query"


def test_run_with_clickhouse_driver_hits_ch_connections_prefix(restore_context):
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"columns": ["n"], "rows": [[1]], "row_count": 1}
    ctx = _FakePluginContext(response=resp)
    _pc.set_context(ctx)

    handler = DialektSQL(_FakeComputer(conn_id="ch-abc", driver="clickhouse"))
    list(handler.run("SELECT 1"))

    assert ctx.last_path == "/ch-connections/ch-abc/query"


def test_run_without_driver_defaults_to_postgres_prefix(restore_context):
    """Backward compatibility — agents bound before the driver field existed
    have no _dialekt_sql_driver attribute; we must not break them.
    """
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"columns": [], "rows": [], "row_count": 0}
    ctx = _FakePluginContext(response=resp)
    _pc.set_context(ctx)

    handler = DialektSQL(_FakeComputer(conn_id="legacy-pg"))  # driver=None
    list(handler.run("SELECT 1"))

    assert ctx.last_path == "/connections/legacy-pg/query"
