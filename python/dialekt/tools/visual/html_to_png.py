"""HTML → PNG via Playwright headless Chromium.

Replaces every ``{{KEY}}`` token in the source HTML with the matching value
from ``variables`` (HTML-escaped) and screenshots the result at the exact
template viewport. Pure function: no FastAPI / registry coupling, so the
renderer can be reused by tests, CLI tools, and future MCP wrappers.
"""

from __future__ import annotations

import html as _html
import re
from pathlib import Path
from typing import Mapping

from playwright.sync_api import sync_playwright


_TOKEN_RE = re.compile(r"\{\{([A-Z][A-Z0-9_]*)\}\}")


def substitute_variables(html: str, variables: Mapping[str, str]) -> str:
    """Replace ``{{KEY}}`` tokens with HTML-escaped values.

    Tokens with no matching key are blanked, not left as ``{{KEY}}`` —
    a half-rendered template leaking braces into the screenshot is worse
    than a clean blank slot.
    """

    def _sub(match: re.Match[str]) -> str:
        key = match.group(1)
        value = variables.get(key, "")
        return _html.escape(str(value), quote=False)

    return _TOKEN_RE.sub(_sub, html)


def render_template(
    html_path: str | Path,
    variables: Mapping[str, str],
    output_path: str | Path,
    width: int,
    height: int,
    *,
    network_wait_ms: int = 1500,
    device_scale_factor: float = 1.0,
) -> str:
    """Render an HTML template to PNG at the exact viewport.

    Args:
        html_path: source HTML file with ``{{KEY}}`` placeholders.
        variables: mapping of placeholder name → value.
        output_path: destination PNG path (parent dirs are created).
        width / height: viewport in CSS pixels.
        network_wait_ms: extra wait after ``networkidle`` for web fonts.
        device_scale_factor: 1.0 = 1080×1920 native, 2.0 = 2× retina.

    Returns the absolute output path.
    """

    html_file = Path(html_path).expanduser().resolve()
    if not html_file.exists():
        raise FileNotFoundError(f"template html not found: {html_file}")

    out_file = Path(output_path).expanduser().resolve()
    out_file.parent.mkdir(parents=True, exist_ok=True)

    rendered_html = substitute_variables(html_file.read_text(encoding="utf-8"), variables)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            context = browser.new_context(
                viewport={"width": width, "height": height},
                device_scale_factor=device_scale_factor,
            )
            page = context.new_page()
            page.set_content(
                rendered_html,
                wait_until="networkidle",
                # base_url lets relative asset paths in the template resolve
                # against the template's own directory.
            )
            # Web fonts (Google Fonts) often resolve after networkidle fires;
            # give them a beat so the screenshot sees the right typography.
            if network_wait_ms > 0:
                page.wait_for_timeout(network_wait_ms)
            page.screenshot(path=str(out_file), full_page=False, omit_background=False)
        finally:
            browser.close()

    return str(out_file)
