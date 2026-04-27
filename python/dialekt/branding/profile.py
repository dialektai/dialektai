"""Brand profile model + filesystem-backed CRUD.

Storage layout (all under DIALEKT_VISUAL_ROOT, defaults to
``~/.dialekt/visual``)::

    visual/
      brands/<id>.json                 — profile metadata + asset refs
      templates/<id>/assets/logo.<ext> — uploaded logo
      templates/<id>/assets/font.<ext> — uploaded font (optional)

Asset paths inside the JSON are stored RELATIVE to ``VISUAL_ROOT`` so a
backup tarball is portable across machines. The runtime resolves them
back to absolute paths via ``BrandProfile.absolute_*`` properties.
"""
from __future__ import annotations

import base64
import json
import os
import re
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# Lazy lookup so tests can monkeypatch DIALEKT_VISUAL_ROOT *after* import.
def _visual_root() -> Path:
    raw = os.environ.get("DIALEKT_VISUAL_ROOT")
    return Path(raw) if raw else Path.home() / ".dialekt" / "visual"


def _brands_root() -> Path:
    return _visual_root() / "brands"


def _assets_root() -> Path:
    return _visual_root() / "templates"


# Public re-exports — backwards-compat for callers that imported the
# module-level constants when they were eagerly evaluated.
BRANDS_ROOT = _brands_root()
ASSETS_ROOT = _assets_root()


_HEX_RE = re.compile(r"^#?([0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")
_BRAND_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,62}$")

_LOGO_EXTS = {"png", "svg", "jpg", "jpeg", "webp"}
_FONT_EXTS = {"ttf", "otf", "woff", "woff2"}

_LOGO_MIME = {
    "png": "image/png",
    "svg": "image/svg+xml",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "webp": "image/webp",
}
_FONT_MIME = {
    "ttf": "font/ttf",
    "otf": "font/otf",
    "woff": "font/woff",
    "woff2": "font/woff2",
}


class BrandNotFoundError(KeyError):
    """Raised when ``load_brand`` cannot resolve a brand_id."""


class BrandValidationError(ValueError):
    """Raised on bad input — invalid hex, unsupported file extension,
    malformed brand_id, etc."""


def coerce_hex(value: str | None, *, fallback: str | None = None) -> str | None:
    """Normalise a hex color to ``#RRGGBB`` (uppercase). Returns
    ``fallback`` if value is empty / None. Raises BrandValidationError
    on garbage input.

    Three-char shorthand (``#abc``) is expanded. Eight-char with alpha
    (``#RRGGBBAA``) is preserved as-is so brand-side translucency works.
    """
    if value is None or value == "":
        return fallback
    s = value.strip()
    m = _HEX_RE.match(s)
    if not m:
        raise BrandValidationError(f"invalid hex color: {value!r}")
    body = m.group(1)
    if len(body) == 3:
        body = "".join(c * 2 for c in body)
    return "#" + body.upper()


def _validate_brand_id(brand_id: str) -> None:
    if not _BRAND_ID_RE.match(brand_id):
        raise BrandValidationError(
            f"brand_id must be 1-63 chars of [a-z0-9_-], starting with "
            f"[a-z0-9]: {brand_id!r}"
        )


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class BrandColors:
    """Four canonical brand colors. ``secondary`` may be empty when a
    brand only specifies a primary/text/background trio."""

    primary: str
    secondary: str = ""
    background: str = "#FFFFFF"
    text: str = "#111111"

    def to_dict(self) -> dict[str, str]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "BrandColors":
        d = data or {}
        return cls(
            primary=coerce_hex(d.get("primary"), fallback="#000000") or "#000000",
            secondary=coerce_hex(d.get("secondary"), fallback="") or "",
            background=coerce_hex(d.get("background"), fallback="#FFFFFF") or "#FFFFFF",
            text=coerce_hex(d.get("text"), fallback="#111111") or "#111111",
        )


@dataclass
class BrandProfile:
    id: str
    name: str
    colors: BrandColors
    logo_rel_path: str = ""           # relative to VISUAL_ROOT
    font_rel_path: str = ""           # relative to VISUAL_ROOT
    font_family: str = ""             # CSS font-family alias
    created_at: str = ""
    updated_at: str = ""
    extras: dict[str, Any] = field(default_factory=dict)

    # ── Persistence ──────────────────────────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "colors": self.colors.to_dict(),
            "logo_rel_path": self.logo_rel_path,
            "font_rel_path": self.font_rel_path,
            "font_family": self.font_family,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "extras": self.extras,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "BrandProfile":
        return cls(
            id=str(data["id"]),
            name=str(data.get("name") or data["id"]),
            colors=BrandColors.from_dict(data.get("colors")),
            logo_rel_path=str(data.get("logo_rel_path") or ""),
            font_rel_path=str(data.get("font_rel_path") or ""),
            font_family=str(data.get("font_family") or ""),
            created_at=str(data.get("created_at") or ""),
            updated_at=str(data.get("updated_at") or ""),
            extras=dict(data.get("extras") or {}),
        )

    # ── Resolved paths (read at runtime so VISUAL_ROOT changes are
    #    honoured between calls — important for the test fixture) ────

    @property
    def absolute_logo_path(self) -> Path | None:
        return (_visual_root() / self.logo_rel_path) if self.logo_rel_path else None

    @property
    def absolute_font_path(self) -> Path | None:
        return (_visual_root() / self.font_rel_path) if self.font_rel_path else None

    # ── Asset I/O (used by the upload endpoint) ──────────────────────

    def write_logo(self, *, data: bytes, ext: str) -> str:
        ext = (ext or "").lower().lstrip(".")
        if ext not in _LOGO_EXTS:
            raise BrandValidationError(
                f"unsupported logo extension: {ext!r} "
                f"(allowed: {sorted(_LOGO_EXTS)})"
            )
        target = _assets_root() / self.id / "assets" / f"logo.{ext}"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        # Clear any older logo with a different extension so /branding/{id}
        # never serves a stale asset after the user replaces a PNG with SVG.
        for sibling in target.parent.glob("logo.*"):
            if sibling != target:
                try:
                    sibling.unlink()
                except OSError:
                    pass
        rel = target.relative_to(_visual_root())
        self.logo_rel_path = str(rel)
        return str(rel)

    def write_font(self, *, data: bytes, ext: str, family: str | None = None) -> str:
        ext = (ext or "").lower().lstrip(".")
        if ext not in _FONT_EXTS:
            raise BrandValidationError(
                f"unsupported font extension: {ext!r} "
                f"(allowed: {sorted(_FONT_EXTS)})"
            )
        target = _assets_root() / self.id / "assets" / f"font.{ext}"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        for sibling in target.parent.glob("font.*"):
            if sibling != target:
                try:
                    sibling.unlink()
                except OSError:
                    pass
        rel = target.relative_to(_visual_root())
        self.font_rel_path = str(rel)
        # The CSS @font-face family alias defaults to "BrandFont" so
        # templates can hard-code ``font-family: 'BrandFont'`` without
        # caring about the upload's actual filename.
        self.font_family = (family or self.font_family or "BrandFont").strip() or "BrandFont"
        return str(rel)

    # ── CSS prelude (consumed by the visual renderer) ────────────────

    def css_prelude(self) -> str:
        """Return a ``<style>`` block that exposes the brand to a
        template via CSS variables, a ``.brand-logo`` background image,
        and an ``@font-face`` declaration when a font is uploaded.

        Logos and fonts are inlined as base64 data URIs so the
        rendered HTML is fully self-contained — Playwright's
        ``set_content`` does not resolve relative paths, so any
        external reference would silently 404."""
        lines: list[str] = ["<style>"]
        lines.append(":root {")
        lines.append(f"  --brand-primary: {self.colors.primary};")
        if self.colors.secondary:
            lines.append(f"  --brand-secondary: {self.colors.secondary};")
        lines.append(f"  --brand-background: {self.colors.background};")
        lines.append(f"  --brand-text: {self.colors.text};")
        lines.append("}")

        logo_p = self.absolute_logo_path
        if logo_p and logo_p.exists():
            ext = logo_p.suffix.lstrip(".").lower()
            mime = _LOGO_MIME.get(ext, "application/octet-stream")
            b64 = base64.b64encode(logo_p.read_bytes()).decode("ascii")
            lines.append(".brand-logo {")
            lines.append(f"  background-image: url('data:{mime};base64,{b64}');")
            lines.append("  background-size: contain;")
            lines.append("  background-repeat: no-repeat;")
            lines.append("  background-position: center;")
            lines.append("}")

        font_p = self.absolute_font_path
        if font_p and font_p.exists():
            ext = font_p.suffix.lstrip(".").lower()
            mime = _FONT_MIME.get(ext, "application/octet-stream")
            b64 = base64.b64encode(font_p.read_bytes()).decode("ascii")
            family = self.font_family or "BrandFont"
            lines.append("@font-face {")
            lines.append(f"  font-family: '{family}';")
            lines.append(f"  src: url('data:{mime};base64,{b64}');")
            lines.append("  font-display: block;")
            lines.append("}")
            lines.append(":root { --brand-font: '" + family + "'; }")

        lines.append("</style>")
        return "\n".join(lines)


# ── Module-level CRUD ──────────────────────────────────────────────────


def save_brand(profile: BrandProfile) -> BrandProfile:
    """Persist (create or overwrite) a brand profile to disk."""
    _validate_brand_id(profile.id)
    if not profile.name:
        raise BrandValidationError("brand name must not be empty")
    if not profile.created_at:
        profile.created_at = _now_iso()
    profile.updated_at = _now_iso()

    target = _brands_root() / f"{profile.id}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(profile.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return profile


def load_brand(brand_id: str) -> BrandProfile:
    """Load a brand by id. Raises BrandNotFoundError on miss."""
    _validate_brand_id(brand_id)
    target = _brands_root() / f"{brand_id}.json"
    if not target.exists():
        raise BrandNotFoundError(brand_id)
    data = json.loads(target.read_text(encoding="utf-8"))
    return BrandProfile.from_dict(data)


def list_brands() -> list[BrandProfile]:
    """Return all stored brands. Files that fail to parse are skipped
    with a warning so one corrupt JSON does not nuke the whole list."""
    root = _brands_root()
    if not root.exists():
        return []
    out: list[BrandProfile] = []
    for f in sorted(root.glob("*.json")):
        try:
            out.append(BrandProfile.from_dict(json.loads(f.read_text("utf-8"))))
        except (json.JSONDecodeError, KeyError, BrandValidationError):
            continue
    return out


def delete_brand(brand_id: str) -> bool:
    """Remove the JSON profile + asset directory. Idempotent."""
    _validate_brand_id(brand_id)
    target = _brands_root() / f"{brand_id}.json"
    existed = target.exists()
    if existed:
        target.unlink()
    assets = _assets_root() / brand_id
    if assets.exists():
        # Walk + unlink — safer than shutil.rmtree against a hostile
        # filesystem (symlinks pointing outside the tree would follow).
        for path in sorted(assets.rglob("*"), reverse=True):
            try:
                if path.is_dir():
                    path.rmdir()
                else:
                    path.unlink()
            except OSError:
                pass
        try:
            assets.rmdir()
        except OSError:
            pass
    return existed


def brand_css_prelude(brand_id: str | None) -> str:
    """Convenience for the visual renderer: load brand by id (if given)
    and return its CSS prelude. Empty string if brand_id is None."""
    if not brand_id:
        return ""
    try:
        return load_brand(brand_id).css_prelude()
    except BrandNotFoundError:
        return ""
