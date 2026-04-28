"""Visual content tools for the MCP server.

Three tools wrap the existing :mod:`dialekt.tools.visual.template_
registry` so an agent can:

- ``dialekt_list_templates`` — discover the templates installed
  under ``~/.dialekt/visual/templates/`` (set + template id, size,
  variables and which are required).
- ``dialekt_render_template`` — render a single PNG into either a
  caller-supplied output path or the engine's default
  ``~/.dialekt/visual/out/`` directory.
- ``dialekt_render_carousel`` — render N slides of the same
  template (one fields-dict per slide) into a folder, named
  ``slide_NN.png``. The folder is created if missing.

Path safety: when the caller passes ``output_path`` (single render)
or ``output_folder`` (carousel), the path is validated against
``server.config.allowed_file_roots`` using the same ``_resolve_safe``
guard the file tools use, so the visual surface can't write
outside the working-directory boundaries the agent has been given.

Default output paths (when no path is passed) land in
``~/.dialekt/visual/out/``, which is a dialekt-managed directory
and not subject to allow-list checks. Agents that want the
generated PNG inside their own workspace must pass an explicit
path.
"""
from __future__ import annotations

import logging
import time
import uuid
from pathlib import Path
from typing import Any, Mapping, Optional, TYPE_CHECKING

from dialekt.mcp.server.tools._wrap import call_tool_wrapped
from dialekt.mcp.server.tools.file import (
    PathAccessDenied,
    _resolve_safe,
)
from dialekt.tools.visual import template_registry

if TYPE_CHECKING:
    from dialekt.mcp.server.server import MCPServer


log = logging.getLogger("dialekt.mcp.server.tools.visual")


def _serialise_template(t) -> dict:
    """Project a :class:`Template` dataclass into a JSON-friendly
    dict for the tool surface."""
    return {
        "id": t.id,
        "set": t.set_name,
        "name": t.name,
        "description": t.description,
        "width": t.width,
        "height": t.height,
        "variables": t.variables,
        "required_variables": t.required_variables,
    }


def _resolve_output_path_optional(
    server: "MCPServer", path: Optional[str]
) -> tuple[Optional[Path], Optional[dict]]:
    """When ``path`` is provided, validate it against the live
    allow-list. Returns ``(resolved_path, error_dict)`` — exactly
    one is non-None."""
    if path is None:
        return None, None
    try:
        safe = _resolve_safe(path, list(server.config.allowed_file_roots))
    except PathAccessDenied as e:
        return None, {
            "error": True,
            "reason": "path_access_denied",
            "detail": str(e),
        }
    return safe, None


def register_visual_tools(server: "MCPServer") -> list[str]:
    """Attach the three visual tools."""
    registered: list[str] = []

    @server.fastmcp.tool(
        description=(
            "List all visual templates installed under "
            "~/.dialekt/visual/templates/. Returns "
            "``{templates: [{id, set, name, description, width, height, "
            "variables, required_variables}], count}``. Use the ``id`` "
            "value (e.g. ``default.announcement_1x1``) when calling "
            "dialekt_render_template / dialekt_render_carousel."
        )
    )
    def dialekt_list_templates() -> dict:
        def _handler() -> dict:
            templates = template_registry.list_templates()
            return {
                "count": len(templates),
                "templates": [_serialise_template(t) for t in templates],
            }

        return call_tool_wrapped(server, "dialekt_list_templates", _handler)

    registered.append("dialekt_list_templates")

    @server.fastmcp.tool(
        description=(
            "Render a single visual template to PNG. ``template_id`` is "
            "the ``set.name`` from dialekt_list_templates. ``fields`` "
            "supplies the template's variables (see required_variables "
            "in the template metadata). ``output_path``, when given, "
            "must be inside the server's allow-list (typically the "
            "agent's working_directory) — otherwise the PNG lands in "
            "~/.dialekt/visual/out/. Optional ``brand_id`` applies a "
            "saved brand profile's CSS prelude. Returns "
            "``{file, size_bytes, ms, template_id, width, height, brand_id}``."
        )
    )
    def dialekt_render_template(
        template_id: str,
        fields: Optional[Mapping[str, Any]] = None,
        output_path: Optional[str] = None,
        brand_id: Optional[str] = None,
    ) -> dict:
        def _handler() -> dict:
            resolved, err = _resolve_output_path_optional(server, output_path)
            if err is not None:
                return err
            try:
                result = template_registry.render(
                    template_id,
                    fields or {},
                    output_path=resolved,
                    brand_id=brand_id,
                )
            except template_registry.TemplateNotFoundError:
                return {
                    "error": True,
                    "reason": "template_not_found",
                    "template_id": template_id,
                }
            except template_registry.TemplateValidationError as e:
                return {
                    "error": True,
                    "reason": "invalid_fields",
                    "detail": str(e),
                }
            return {
                "file": result["file"],
                "size_bytes": result["size_bytes"],
                "ms": result["ms"],
                "template_id": result["template_id"],
                "width": result["width"],
                "height": result["height"],
                "brand_id": result["brand_id"],
            }

        return call_tool_wrapped(
            server,
            "dialekt_render_template",
            _handler,
            extra_audit={"template_id": template_id, "brand_id": brand_id},
        )

    registered.append("dialekt_render_template")

    @server.fastmcp.tool(
        description=(
            "Render N slides of the same template into a folder. "
            "``slides`` is a list of fields dicts (one per slide). "
            "``output_folder`` must resolve inside the server's "
            "allow-list — typically ``{workspace}/media/carousel/"
            "{date}-{name}``. Files are written as ``slide_NN.png`` "
            "(zero-padded). Returns "
            "``{folder, files: [...], count, ms, template_id, brand_id}``."
        )
    )
    def dialekt_render_carousel(
        template_id: str,
        slides: list[Mapping[str, Any]],
        output_folder: str,
        brand_id: Optional[str] = None,
    ) -> dict:
        def _handler() -> dict:
            if not isinstance(slides, list) or not slides:
                return {
                    "error": True,
                    "reason": "invalid_slides",
                    "detail": "slides must be a non-empty list of field dicts",
                }
            try:
                folder = _resolve_safe(
                    output_folder, list(server.config.allowed_file_roots)
                )
            except PathAccessDenied as e:
                return {
                    "error": True,
                    "reason": "path_access_denied",
                    "detail": str(e),
                }
            try:
                folder.mkdir(parents=True, exist_ok=True)
            except OSError as e:
                return {
                    "error": True,
                    "reason": "folder_create_failed",
                    "detail": str(e),
                }

            started = time.perf_counter()
            files: list[str] = []
            for idx, slide_fields in enumerate(slides, start=1):
                target = folder / f"slide_{idx:02d}.png"
                try:
                    result = template_registry.render(
                        template_id,
                        slide_fields,
                        output_path=target,
                        brand_id=brand_id,
                    )
                except template_registry.TemplateNotFoundError:
                    return {
                        "error": True,
                        "reason": "template_not_found",
                        "template_id": template_id,
                        "rendered_files": files,
                    }
                except template_registry.TemplateValidationError as e:
                    return {
                        "error": True,
                        "reason": "invalid_fields",
                        "slide_index": idx,
                        "detail": str(e),
                        "rendered_files": files,
                    }
                files.append(result["file"])
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            return {
                "folder": str(folder),
                "files": files,
                "count": len(files),
                "ms": elapsed_ms,
                "template_id": template_id,
                "brand_id": brand_id,
            }

        return call_tool_wrapped(
            server,
            "dialekt_render_carousel",
            _handler,
            extra_audit={
                "template_id": template_id,
                "brand_id": brand_id,
                "slide_count": len(slides) if isinstance(slides, list) else None,
            },
        )

    registered.append("dialekt_render_carousel")

    return registered
