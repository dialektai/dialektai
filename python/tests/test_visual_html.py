"""E2E tests for the HTML → PNG visual engine.

Slow: each test boots a real Playwright/Chromium browser. Marked with
``@pytest.mark.slow`` so the default suite stays fast — opt in with
``pytest -m slow`` or by running the file directly.
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

import pytest
from PIL import Image


# Pin the visual root to a tmp dir BEFORE importing the registry — the env var
# is read at module import. We can't use a fixture here because the module-level
# constant has already captured the value by the time fixtures run.
_TEST_ROOT = Path(tempfile.mkdtemp(prefix="dialekt-visual-test-"))
os.environ["DIALEKT_VISUAL_ROOT"] = str(_TEST_ROOT)

# Copy the in-repo template fixtures into the test root so the suite runs on
# any machine — not only when ~/.dialekt/visual/templates/default exists.
_FIXTURE_TEMPLATES = Path(__file__).parent / "fixtures" / "visual_templates"
if _FIXTURE_TEMPLATES.exists():
    shutil.copytree(_FIXTURE_TEMPLATES, _TEST_ROOT / "templates", dirs_exist_ok=True)

sys.path.insert(0, str(Path(__file__).parent.parent))

from dialekt.tools.visual import list_templates, render  # noqa: E402
from dialekt.tools.visual.html_to_png import substitute_variables  # noqa: E402
from dialekt.tools.visual.template_registry import (  # noqa: E402
    TemplateNotFoundError,
    TemplateValidationError,
)


pytestmark = pytest.mark.slow


def test_substitute_variables_replaces_tokens():
    html = "<h1>{{TITLE}}</h1><p>{{BODY}}</p>"
    out = substitute_variables(html, {"TITLE": "Hello", "BODY": "World"})
    assert out == "<h1>Hello</h1><p>World</p>"


def test_substitute_variables_blanks_missing_keys():
    html = "<h1>{{TITLE}}</h1><span>{{MISSING}}</span>"
    out = substitute_variables(html, {"TITLE": "Hi"})
    assert out == "<h1>Hi</h1><span></span>"


def test_substitute_variables_html_escapes_values():
    html = "<p>{{TEXT}}</p>"
    out = substitute_variables(html, {"TEXT": "<script>x</script>"})
    assert "<script>" not in out
    assert "&lt;script&gt;" in out


def test_registry_discovers_default_templates():
    ids = {t.id for t in list_templates()}
    assert "default.announcement_1x1" in ids
    assert "default.news_4x5" in ids
    assert "default.schedule_9x16" in ids


def test_render_announcement_1x1_produces_correct_png():
    result = render(
        "default.announcement_1x1",
        {
            "EYEBROW": "TEST EYEBROW",
            "TITLE": "Probe Headline",
            "SUBTITLE": "Probe subtitle line",
            "DATE": "2026-04-27",
            "FOOTER": "test.local",
        },
    )

    assert result["ok"] is True
    assert result["template_id"] == "default.announcement_1x1"
    assert result["width"] == 1080
    assert result["height"] == 1080
    assert result["size_bytes"] > 10_000
    assert result["ms"] > 0

    out_path = Path(result["file"])
    assert out_path.exists()

    with Image.open(out_path) as img:
        assert img.size == (1080, 1080)
        assert img.format == "PNG"


def test_render_missing_required_field_raises():
    with pytest.raises(TemplateValidationError):
        render("default.announcement_1x1", {})  # TITLE is required


def test_render_unknown_field_raises():
    with pytest.raises(TemplateValidationError):
        render(
            "default.announcement_1x1",
            {"TITLE": "ok", "NOT_A_FIELD": "x"},
        )


def test_render_unknown_template_raises():
    with pytest.raises(TemplateNotFoundError):
        render("default.does_not_exist", {"TITLE": "x"})


def test_render_news_4x5_dimensions():
    result = render(
        "default.news_4x5",
        {"HEADLINE": "Probe headline for news template"},
    )
    assert result["width"] == 1080
    assert result["height"] == 1350
    with Image.open(result["file"]) as img:
        assert img.size == (1080, 1350)


def test_render_schedule_9x16_dimensions():
    result = render(
        "default.schedule_9x16",
        {"TITLE": "Probe agenda"},
    )
    assert result["width"] == 1080
    assert result["height"] == 1920
    with Image.open(result["file"]) as img:
        assert img.size == (1080, 1920)
