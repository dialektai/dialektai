"""Tests for ``dialekt.mcp.server.tools.visual``.

The underlying renderer (``template_registry.render``) drives a
Playwright headless Chromium and is exercised by
``test_visual_html.py`` (slow, marked). For the MCP wrapper we
mock both ``list_templates`` and ``render`` so we can hammer the
fast paths — credential resolution, path safety, error
classification — without spinning up a browser per test.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from dialekt.mcp.server import MCPServer, ServerConfig
from dialekt.mcp.server.config import ApiKey
from dialekt.mcp.server.tools._wrap import ToolAccessDenied
from dialekt.mcp.server.tools import visual as visual_tools
from dialekt.mcp.server.tools.visual import register_visual_tools
from dialekt.tools.visual import template_registry


@dataclass(frozen=True)
class FakeTemplate:
    id: str
    set_name: str
    name: str
    description: str
    width: int
    height: int
    variables: dict
    html_path: Path

    @property
    def required_variables(self):
        return [k for k, v in self.variables.items() if v.get("required")]


_SAMPLE_TEMPLATE = FakeTemplate(
    id="default.announcement_1x1",
    set_name="default",
    name="Announcement 1x1",
    description="Square announcement",
    width=1080,
    height=1080,
    variables={
        "title": {"required": True},
        "subtitle": {"required": False, "default": ""},
    },
    html_path=Path("/fake/template.html"),
)


@pytest.fixture
def stub_registry(monkeypatch, tmp_path):
    """Replace template_registry.list_templates and render with
    in-memory fakes so tests don't touch the filesystem (apart from
    the on-disk PNG the carousel test produces) or Playwright."""

    def _list_templates():
        return [_SAMPLE_TEMPLATE]

    def _render(template_id, fields, *, output_path=None, brand_id=None):
        if template_id != _SAMPLE_TEMPLATE.id:
            raise template_registry.TemplateNotFoundError(template_id)
        if "title" not in fields or not fields["title"]:
            raise template_registry.TemplateValidationError(
                "missing required variables: title"
            )
        target = Path(output_path) if output_path else (tmp_path / "auto.png")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 16)
        return {
            "ok": True,
            "file": str(target),
            "files": [str(target)],
            "size_bytes": target.stat().st_size,
            "ms": 1,
            "template_id": template_id,
            "width": _SAMPLE_TEMPLATE.width,
            "height": _SAMPLE_TEMPLATE.height,
            "brand_id": brand_id,
        }

    monkeypatch.setattr(template_registry, "list_templates", _list_templates)
    monkeypatch.setattr(template_registry, "render", _render)
    monkeypatch.setattr(visual_tools.template_registry, "list_templates", _list_templates)
    monkeypatch.setattr(visual_tools.template_registry, "render", _render)
    return tmp_path


def _build_server(allowed_roots=None):
    events: list[dict] = []
    cfg = ServerConfig(allowed_file_roots=allowed_roots or [])
    srv = MCPServer(cfg, audit_callback=lambda **p: events.append(p))
    srv.bind_active_key(ApiKey(id="test", value="x" * 32))
    register_visual_tools(srv)
    return srv, events


# ---------------------------------------------------------------------------
# dialekt_list_templates
# ---------------------------------------------------------------------------


def test_list_templates_returns_serialised_metadata(stub_registry):
    srv, _ = _build_server()
    tool = srv.fastmcp._tool_manager._tools["dialekt_list_templates"].fn
    out = tool()
    assert out["count"] == 1
    t = out["templates"][0]
    assert t["id"] == "default.announcement_1x1"
    assert t["set"] == "default"
    assert t["width"] == 1080
    assert t["required_variables"] == ["title"]


# ---------------------------------------------------------------------------
# dialekt_render_template
# ---------------------------------------------------------------------------


def test_render_template_default_output_path(stub_registry):
    srv, _ = _build_server()
    tool = srv.fastmcp._tool_manager._tools["dialekt_render_template"].fn
    out = tool(
        template_id="default.announcement_1x1",
        fields={"title": "IBA", "subtitle": "live training"},
    )
    assert out.get("error") is not True
    assert out["template_id"] == "default.announcement_1x1"
    assert out["width"] == 1080
    assert Path(out["file"]).exists()


def test_render_template_with_explicit_output_path(stub_registry, tmp_path):
    srv, _ = _build_server(allowed_roots=[str(tmp_path)])
    tool = srv.fastmcp._tool_manager._tools["dialekt_render_template"].fn
    target = tmp_path / "media" / "2026-04-28_iba.png"
    out = tool(
        template_id="default.announcement_1x1",
        fields={"title": "IBA"},
        output_path=str(target),
    )
    assert out.get("error") is not True
    assert Path(out["file"]) == target.resolve()
    assert target.exists()


def test_render_template_rejects_path_outside_root(stub_registry, tmp_path):
    srv, _ = _build_server(allowed_roots=[str(tmp_path)])
    tool = srv.fastmcp._tool_manager._tools["dialekt_render_template"].fn
    out = tool(
        template_id="default.announcement_1x1",
        fields={"title": "IBA"},
        output_path="/tmp/should-not-write-here.png",
    )
    assert out["error"] is True
    assert out["reason"] == "path_access_denied"


def test_render_template_unknown_id(stub_registry):
    srv, _ = _build_server()
    tool = srv.fastmcp._tool_manager._tools["dialekt_render_template"].fn
    out = tool(template_id="missing.template", fields={"title": "x"})
    assert out["error"] is True
    assert out["reason"] == "template_not_found"


def test_render_template_missing_required_field(stub_registry):
    srv, _ = _build_server()
    tool = srv.fastmcp._tool_manager._tools["dialekt_render_template"].fn
    out = tool(template_id="default.announcement_1x1", fields={})
    assert out["error"] is True
    assert out["reason"] == "invalid_fields"
    assert "title" in out["detail"]


def test_render_template_audit(stub_registry):
    srv, events = _build_server()
    tool = srv.fastmcp._tool_manager._tools["dialekt_render_template"].fn
    tool(
        template_id="default.announcement_1x1",
        fields={"title": "x"},
        brand_id="iba-2026",
    )
    success = [e for e in events if e.get("result") == "success"]
    assert success
    extra = success[-1]["extra"]
    assert extra["template_id"] == "default.announcement_1x1"
    assert extra["brand_id"] == "iba-2026"


# ---------------------------------------------------------------------------
# dialekt_render_carousel
# ---------------------------------------------------------------------------


def test_render_carousel_writes_each_slide(stub_registry, tmp_path):
    srv, _ = _build_server(allowed_roots=[str(tmp_path)])
    tool = srv.fastmcp._tool_manager._tools["dialekt_render_carousel"].fn
    out = tool(
        template_id="default.announcement_1x1",
        slides=[
            {"title": "slide one"},
            {"title": "slide two"},
            {"title": "slide three"},
        ],
        output_folder=str(tmp_path / "media" / "carousel" / "2026-04-28-launch"),
    )
    assert out.get("error") is not True
    assert out["count"] == 3
    folder = Path(out["folder"])
    assert (folder / "slide_01.png").exists()
    assert (folder / "slide_02.png").exists()
    assert (folder / "slide_03.png").exists()


def test_render_carousel_creates_missing_folder(stub_registry, tmp_path):
    nested = tmp_path / "deep" / "media" / "carousel" / "x"
    srv, _ = _build_server(allowed_roots=[str(tmp_path)])
    tool = srv.fastmcp._tool_manager._tools["dialekt_render_carousel"].fn
    out = tool(
        template_id="default.announcement_1x1",
        slides=[{"title": "a"}],
        output_folder=str(nested),
    )
    assert out.get("error") is not True
    assert nested.is_dir()


def test_render_carousel_rejects_outside_root(stub_registry, tmp_path):
    srv, _ = _build_server(allowed_roots=[str(tmp_path)])
    tool = srv.fastmcp._tool_manager._tools["dialekt_render_carousel"].fn
    out = tool(
        template_id="default.announcement_1x1",
        slides=[{"title": "a"}],
        output_folder="/tmp/escape",
    )
    assert out["error"] is True
    assert out["reason"] == "path_access_denied"


def test_render_carousel_empty_slides(stub_registry, tmp_path):
    srv, _ = _build_server(allowed_roots=[str(tmp_path)])
    tool = srv.fastmcp._tool_manager._tools["dialekt_render_carousel"].fn
    out = tool(
        template_id="default.announcement_1x1",
        slides=[],
        output_folder=str(tmp_path / "out"),
    )
    assert out["error"] is True
    assert out["reason"] == "invalid_slides"


def test_render_carousel_partial_failure_returns_what_was_written(stub_registry, tmp_path):
    srv, _ = _build_server(allowed_roots=[str(tmp_path)])
    tool = srv.fastmcp._tool_manager._tools["dialekt_render_carousel"].fn
    out = tool(
        template_id="default.announcement_1x1",
        slides=[
            {"title": "ok"},
            {},  # missing required title — fails on slide 2
        ],
        output_folder=str(tmp_path / "out"),
    )
    assert out["error"] is True
    assert out["reason"] == "invalid_fields"
    assert out["slide_index"] == 2
    # Slide 1 was rendered before the failure.
    assert len(out["rendered_files"]) == 1


def test_render_carousel_audit_records_slide_count(stub_registry, tmp_path):
    srv, events = _build_server(allowed_roots=[str(tmp_path)])
    tool = srv.fastmcp._tool_manager._tools["dialekt_render_carousel"].fn
    tool(
        template_id="default.announcement_1x1",
        slides=[{"title": "a"}, {"title": "b"}],
        output_folder=str(tmp_path / "out"),
    )
    success = [e for e in events if e.get("result") == "success"]
    assert success
    assert success[-1]["extra"]["slide_count"] == 2


# ---------------------------------------------------------------------------
# category gate
# ---------------------------------------------------------------------------


def test_visual_category_disabled_refuses(stub_registry):
    events: list[dict] = []
    srv = MCPServer(
        ServerConfig(enabled_categories=["database"]),
        audit_callback=lambda **p: events.append(p),
    )
    srv.bind_active_key(ApiKey(id="test", value="x" * 32))
    register_visual_tools(srv)
    tool = srv.fastmcp._tool_manager._tools["dialekt_list_templates"].fn
    with pytest.raises(ToolAccessDenied):
        tool()
    denied = [e for e in events if e.get("result") == "permission_denied"]
    assert len(denied) == 1
