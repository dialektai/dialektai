"""Tests for dialekt.mcp.server.tools.file.

Heavy focus on the path-safety logic — this is the highest-risk
tool surface (arbitrary file reads) so the allow-list tests are
the security contract of the tool.
"""
import os
from pathlib import Path

import pytest

from dialekt.mcp.server import MCPServer, ServerConfig
from dialekt.mcp.server.config import ApiKey
from dialekt.mcp.server.tools._wrap import ToolAccessDenied
from dialekt.mcp.server.tools.file import (
    PathAccessDenied,
    _resolve_safe,
    register_file_tools,
)


def _build_server(allowed_roots: list[str]):
    events: list[dict] = []
    srv = MCPServer(
        ServerConfig(allowed_file_roots=allowed_roots),
        audit_callback=lambda **p: events.append(p),
    )
    srv.bind_active_key(ApiKey(id="test", value="x" * 32))
    register_file_tools(srv)
    return srv, events


# ---------------------------------------------------------------------------
# _resolve_safe — the core security check.
# ---------------------------------------------------------------------------


def test_resolve_safe_accepts_path_inside_root(tmp_path):
    target = tmp_path / "inside.txt"
    target.touch()
    out = _resolve_safe(str(target), [str(tmp_path)])
    assert out == target.resolve()


def test_resolve_safe_rejects_empty_roots(tmp_path):
    """allowed_roots=[] means file tools effectively disabled."""
    with pytest.raises(PathAccessDenied, match="empty"):
        _resolve_safe(str(tmp_path / "anything"), [])


def test_resolve_safe_rejects_directory_traversal(tmp_path):
    traversal = str(tmp_path / ".." / ".." / "etc" / "passwd")
    with pytest.raises(PathAccessDenied, match="outside"):
        _resolve_safe(traversal, [str(tmp_path)])


def test_resolve_safe_rejects_outside_root_explicit(tmp_path):
    with pytest.raises(PathAccessDenied):
        _resolve_safe("/etc/passwd", [str(tmp_path)])


def test_resolve_safe_rejects_symlink_pointing_outside(tmp_path):
    """A symlink inside an allowed root pointing OUTSIDE that root
    must be rejected after realpath resolution."""
    outside = tmp_path.parent / "outside_target"
    outside.mkdir(exist_ok=True)
    (outside / "secret").write_text("forbidden")

    inside = tmp_path / "escape_hatch"
    os.symlink(outside / "secret", inside)

    with pytest.raises(PathAccessDenied):
        _resolve_safe(str(inside), [str(tmp_path)])


def test_resolve_safe_expands_tilde(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / "hello").touch()
    out = _resolve_safe("~/hello", [str(tmp_path)])
    assert out.name == "hello"


def test_resolve_safe_accepts_nonexistent_path_if_inside_root(tmp_path):
    """strict=False — we still return a resolved path for a file
    that doesn't exist yet so the tool can raise a cleaner
    not_found error, not a cryptic OSError."""
    out = _resolve_safe(str(tmp_path / "does-not-exist-yet"), [str(tmp_path)])
    assert str(out).startswith(str(tmp_path.resolve()))


def test_resolve_safe_multiple_roots_any_match_wins(tmp_path):
    root_a = tmp_path / "a"
    root_b = tmp_path / "b"
    root_a.mkdir()
    root_b.mkdir()
    target = root_b / "in-b.txt"
    target.touch()

    out = _resolve_safe(str(target), [str(root_a), str(root_b)])
    assert out == target.resolve()


# ---------------------------------------------------------------------------
# dialekt_read_file.
# ---------------------------------------------------------------------------


def test_read_file_happy_path(tmp_path):
    target = tmp_path / "hello.txt"
    target.write_text("Hello from dialekt MCP!\n")
    srv, _ = _build_server([str(tmp_path)])

    tool = srv.fastmcp._tool_manager._tools["dialekt_read_file"].fn
    out = tool(path=str(target))
    assert out.get("error") is not True
    assert "Hello from dialekt MCP" in out["content"]
    assert out["size_bytes"] > 0


def test_read_file_outside_root_raises(tmp_path):
    srv, _ = _build_server([str(tmp_path)])
    tool = srv.fastmcp._tool_manager._tools["dialekt_read_file"].fn
    with pytest.raises(PathAccessDenied):
        tool(path="/etc/passwd")


def test_read_file_nonexistent_returns_structured_error(tmp_path):
    srv, _ = _build_server([str(tmp_path)])
    tool = srv.fastmcp._tool_manager._tools["dialekt_read_file"].fn
    out = tool(path=str(tmp_path / "nope.txt"))
    assert out["error"] is True
    assert out["reason"] == "not_found"


def test_read_file_directory_returns_structured_error(tmp_path):
    subdir = tmp_path / "sub"
    subdir.mkdir()
    srv, _ = _build_server([str(tmp_path)])
    tool = srv.fastmcp._tool_manager._tools["dialekt_read_file"].fn
    out = tool(path=str(subdir))
    assert out["error"] is True
    assert out["reason"] == "not_a_file"


def test_read_file_binary_returns_not_utf8(tmp_path):
    target = tmp_path / "binary.bin"
    target.write_bytes(b"\xff\xfe\x00\x01\x02not-valid-utf8\x80\x81")
    srv, _ = _build_server([str(tmp_path)])
    tool = srv.fastmcp._tool_manager._tools["dialekt_read_file"].fn
    out = tool(path=str(target))
    assert out["error"] is True
    assert out["reason"] == "not_utf8"


def test_read_file_empty_roots_raises_access_denied(tmp_path):
    srv, _ = _build_server([])  # default empty
    tool = srv.fastmcp._tool_manager._tools["dialekt_read_file"].fn
    with pytest.raises(PathAccessDenied, match="empty"):
        tool(path=str(tmp_path / "any.txt"))


# ---------------------------------------------------------------------------
# dialekt_list_directory.
# ---------------------------------------------------------------------------


def test_list_directory_happy_path(tmp_path):
    (tmp_path / "a.txt").write_text("a")
    (tmp_path / "b.txt").write_text("bb")
    (tmp_path / "sub").mkdir()

    srv, _ = _build_server([str(tmp_path)])
    tool = srv.fastmcp._tool_manager._tools["dialekt_list_directory"].fn
    out = tool(path=str(tmp_path))
    assert out.get("error") is not True
    names = {e["name"] for e in out["entries"]}
    assert names == {"a.txt", "b.txt", "sub"}

    types = {e["name"]: e["type"] for e in out["entries"]}
    assert types["sub"] == "dir"
    assert types["a.txt"] == "file"


def test_list_directory_outside_root_raises(tmp_path):
    srv, _ = _build_server([str(tmp_path)])
    tool = srv.fastmcp._tool_manager._tools["dialekt_list_directory"].fn
    with pytest.raises(PathAccessDenied):
        tool(path="/etc")


def test_list_directory_on_file_returns_error(tmp_path):
    target = tmp_path / "file.txt"
    target.write_text("x")
    srv, _ = _build_server([str(tmp_path)])
    tool = srv.fastmcp._tool_manager._tools["dialekt_list_directory"].fn
    out = tool(path=str(target))
    assert out["error"] is True
    assert out["reason"] == "not_a_directory"


# ---------------------------------------------------------------------------
# Audit emission.
# ---------------------------------------------------------------------------


def test_success_emits_audit(tmp_path):
    target = tmp_path / "f.txt"
    target.write_text("content")
    srv, events = _build_server([str(tmp_path)])
    tool = srv.fastmcp._tool_manager._tools["dialekt_read_file"].fn
    tool(path=str(target))
    success = [e for e in events if e.get("result") == "success"]
    assert len(success) == 1
    assert success[0]["action"] == "dialekt_read_file"
    assert success[0]["extra"]["requested_path"] == str(target)


def test_path_denied_emits_error_audit(tmp_path):
    srv, events = _build_server([str(tmp_path)])
    tool = srv.fastmcp._tool_manager._tools["dialekt_read_file"].fn
    with pytest.raises(PathAccessDenied):
        tool(path="/etc/passwd")
    errors = [e for e in events if e.get("result") == "error"]
    assert len(errors) == 1
    assert errors[0]["error_kind"] == "PathAccessDenied"


def test_category_disabled_refuses_with_permission_denied(tmp_path):
    """Category gate rejects before the handler runs."""
    events: list[dict] = []
    srv = MCPServer(
        ServerConfig(
            allowed_file_roots=[str(tmp_path)],
            enabled_categories=["database"],  # file disabled
        ),
        audit_callback=lambda **p: events.append(p),
    )
    srv.bind_active_key(ApiKey(id="test", value="x" * 32))
    register_file_tools(srv)

    tool = srv.fastmcp._tool_manager._tools["dialekt_read_file"].fn
    with pytest.raises(ToolAccessDenied):
        tool(path=str(tmp_path / "anything"))
    denied = [e for e in events if e.get("result") == "permission_denied"]
    assert len(denied) == 1
