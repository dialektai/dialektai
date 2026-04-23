"""Tests for the DialektSQL Open Interpreter language handler."""
from unittest.mock import MagicMock, patch

import pytest

from dialekt.llm.sql_language import DialektSQL, _format_result


class _FakeInterpreter:
    def __init__(self, conn_id=None):
        self._dialekt_sql_conn = conn_id


class _FakeComputer:
    def __init__(self, conn_id=None):
        self.interpreter = _FakeInterpreter(conn_id)


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


def test_run_with_binding_calls_backend_and_formats_output():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "columns": ["count"],
        "rows": [[42]],
        "row_count": 1,
    }
    mock_client = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client.post = MagicMock(return_value=mock_resp)

    with patch("httpx.Client", return_value=mock_client):
        handler = DialektSQL(_FakeComputer(conn_id="conn-123"))
        chunks = list(handler.run("SELECT COUNT(*) FROM orders"))

    mock_client.post.assert_called_once()
    call_url = mock_client.post.call_args[0][0]
    call_body = mock_client.post.call_args[1]["json"]
    assert "connections/conn-123/query" in call_url
    # retry:false avoids triggering the server-side recursive validate loop.
    assert call_body == {"sql": "SELECT COUNT(*) FROM orders", "retry": False}
    assert len(chunks) == 1
    content = chunks[0]["content"]
    assert "42" in content
    assert "count" in content


def test_run_with_backend_4xx_surfaces_error():
    mock_resp = MagicMock()
    mock_resp.status_code = 400
    mock_resp.text = "syntax error at or near FROMM"
    mock_client = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client.post = MagicMock(return_value=mock_resp)

    with patch("httpx.Client", return_value=mock_client):
        handler = DialektSQL(_FakeComputer(conn_id="conn-123"))
        chunks = list(handler.run("SELECT * FROMM orders"))

    assert len(chunks) == 1
    assert "SQL error (400)" in chunks[0]["content"]
    assert "syntax error" in chunks[0]["content"]


def test_run_with_transport_error_surfaces_it():
    import httpx

    def boom(*a, **kw):
        raise httpx.ConnectError("could not reach backend")

    with patch("httpx.Client", side_effect=boom):
        handler = DialektSQL(_FakeComputer(conn_id="conn-123"))
        chunks = list(handler.run("SELECT 1"))

    assert len(chunks) == 1
    assert "SQL transport error" in chunks[0]["content"]
