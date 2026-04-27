"""Template registry — discovers HTML templates by scanning the visual root.

Layout::

    ~/.dialekt/visual/
      templates/
        <set>/                      # e.g. "default", "iba", "<pilot_id>"
          <template>/
            template.html           # body of the template (or path from manifest)
            manifest.json           # id, size, variables schema
      out/                          # rendered PNGs

Adding a new template = drop a directory with ``template.html`` +
``manifest.json``. The registry will pick it up on next ``list_templates()``
call. No code edits required.

Template IDs use ``<set>.<template>`` so the same name can live under
multiple sets (e.g. ``default.announcement_1x1`` vs ``iba.announcement_1x1``).
"""

from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from .html_to_png import render_template


VISUAL_ROOT = Path(os.environ.get("DIALEKT_VISUAL_ROOT", Path.home() / ".dialekt" / "visual"))


class TemplateNotFoundError(KeyError):
    """Raised when a template_id cannot be resolved."""


class TemplateValidationError(ValueError):
    """Raised when required variables are missing or extra keys are passed."""


@dataclass(frozen=True)
class Template:
    id: str
    set_name: str
    name: str
    width: int
    height: int
    html_path: Path
    variables: dict[str, dict[str, Any]] = field(default_factory=dict)
    description: str = ""

    @property
    def required_variables(self) -> list[str]:
        return [k for k, v in self.variables.items() if v.get("required")]

    @property
    def defaults(self) -> dict[str, str]:
        return {
            k: str(v.get("default", ""))
            for k, v in self.variables.items()
            if not v.get("required")
        }


def _templates_dir() -> Path:
    return VISUAL_ROOT / "templates"


def _out_dir() -> Path:
    out = VISUAL_ROOT / "out"
    out.mkdir(parents=True, exist_ok=True)
    return out


def _load_manifest(template_dir: Path, set_name: str) -> Template | None:
    manifest = template_dir / "manifest.json"
    if not manifest.exists():
        return None
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None

    template_name = template_dir.name
    template_id = data.get("id") or f"{set_name}.{template_name}"
    html_rel = data.get("html", "template.html")
    html_path = (template_dir / html_rel).resolve()
    if not html_path.exists():
        return None

    return Template(
        id=template_id,
        set_name=set_name,
        name=data.get("name", template_name),
        description=data.get("description", ""),
        width=int(data["width"]),
        height=int(data["height"]),
        html_path=html_path,
        variables=data.get("variables", {}),
    )


def list_templates() -> list[Template]:
    """Scan VISUAL_ROOT/templates/ and return all discovered templates."""
    root = _templates_dir()
    if not root.exists():
        return []
    found: list[Template] = []
    for set_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        for tmpl_dir in sorted(p for p in set_dir.iterdir() if p.is_dir()):
            tmpl = _load_manifest(tmpl_dir, set_dir.name)
            if tmpl is not None:
                found.append(tmpl)
    return found


def get_template(template_id: str) -> Template:
    """Resolve a ``<set>.<template>`` id. Raises TemplateNotFoundError on miss."""
    for tmpl in list_templates():
        if tmpl.id == template_id:
            return tmpl
    raise TemplateNotFoundError(template_id)


def _validate_fields(tmpl: Template, fields: Mapping[str, Any]) -> dict[str, str]:
    """Apply defaults, check required keys, return a string-coerced map."""
    merged = dict(tmpl.defaults)
    for key, value in fields.items():
        if key not in tmpl.variables:
            raise TemplateValidationError(f"unknown variable: {key!r}")
        merged[key] = "" if value is None else str(value)

    missing = [k for k in tmpl.required_variables if not merged.get(k)]
    if missing:
        raise TemplateValidationError(
            f"missing required variables: {', '.join(sorted(missing))}"
        )
    return merged


def render(
    template_id: str,
    fields: Mapping[str, Any],
    *,
    output_path: str | Path | None = None,
    brand_id: str | None = None,
) -> dict[str, Any]:
    """Render a template by id. Returns a dict with file path + timing.

    Output file lands in ``VISUAL_ROOT/out/<template_id>_<token>.png`` unless
    ``output_path`` is given explicitly.

    When ``brand_id`` is provided, the matching brand profile's CSS
    prelude (variables, ``.brand-logo``, ``@font-face``) is prepended
    to the template HTML before screenshot. Templates that don't
    reference brand variables render unchanged — opt-in via CSS.
    """
    tmpl = get_template(template_id)
    variables = _validate_fields(tmpl, fields)

    if output_path is None:
        token = uuid.uuid4().hex[:8]
        safe_id = template_id.replace(".", "_")
        output_path = _out_dir() / f"{safe_id}_{token}.png"

    # Lazy import — avoids the visual engine pulling in the branding
    # module if no caller passes a brand_id.
    brand_prelude = ""
    if brand_id:
        from dialekt.branding import brand_css_prelude
        brand_prelude = brand_css_prelude(brand_id)

    started = time.perf_counter()
    file_path = render_template(
        html_path=tmpl.html_path,
        variables=variables,
        output_path=output_path,
        width=tmpl.width,
        height=tmpl.height,
        head_prelude=brand_prelude,
    )
    elapsed_ms = int((time.perf_counter() - started) * 1000)

    size_bytes = Path(file_path).stat().st_size
    return {
        "ok": True,
        "file": file_path,
        "files": [file_path],
        "size_bytes": size_bytes,
        "ms": elapsed_ms,
        "template_id": template_id,
        "width": tmpl.width,
        "height": tmpl.height,
        "brand_id": brand_id,
    }
