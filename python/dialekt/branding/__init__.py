"""Brand profiles — pilot-scope identity assets that shape rendered visuals.

A brand pairs a few hex colors, an optional logo (PNG/SVG), and an
optional font (TTF/OTF/WOFF/WOFF2). Profiles live as JSON under
``~/.dialekt/visual/brands/<brand_id>.json``; the binary assets sit
alongside the visual engine's templates at
``~/.dialekt/visual/templates/<brand_id>/assets/``.

The visual engine consumes a brand at render time via
``dialekt.tools.visual.render(template_id, fields, brand_id=...)``.
Templates that opt in to brand-awareness reference CSS variables
``--brand-primary``, ``--brand-secondary``, ``--brand-background``,
``--brand-text`` and the ``.brand-logo`` image and ``brand-font``
font-family which the renderer injects as base64 data URIs.
"""

from .profile import (
    BRANDS_ROOT,
    ASSETS_ROOT,
    BrandProfile,
    BrandColors,
    BrandNotFoundError,
    BrandValidationError,
    save_brand,
    load_brand,
    list_brands,
    delete_brand,
    brand_css_prelude,
    coerce_hex,
)

__all__ = [
    "BRANDS_ROOT",
    "ASSETS_ROOT",
    "BrandProfile",
    "BrandColors",
    "BrandNotFoundError",
    "BrandValidationError",
    "save_brand",
    "load_brand",
    "list_brands",
    "delete_brand",
    "brand_css_prelude",
    "coerce_hex",
]
