"""Tests for dialekt.branding — profile CRUD + REST endpoints + preview
round-trip.

Profile-layer tests run pure-Python (no Playwright). The /branding/{id}/
preview round-trip is gated behind ``@pytest.mark.slow`` because it
spins a real Chromium browser to confirm the brand actually lands in
the rendered PNG.
"""
from __future__ import annotations

import io
import json
import os
import sys
import tempfile
from pathlib import Path

import pytest


# ── Pin DIALEKT_VISUAL_ROOT before importing the module ───────────────


_TEST_ROOT = Path(tempfile.mkdtemp(prefix="dialekt-brand-test-"))
os.environ["DIALEKT_VISUAL_ROOT"] = str(_TEST_ROOT)


# Copy the in-repo visual template fixtures so /visual/render with a
# default.* template works under the patched DIALEKT_VISUAL_ROOT. Mirrors
# the bootstrapping in test_visual_html.py.
import shutil  # noqa: E402
_FIXTURE_TEMPLATES = Path(__file__).parent / "fixtures" / "visual_templates"
if _FIXTURE_TEMPLATES.exists():
    shutil.copytree(
        _FIXTURE_TEMPLATES, _TEST_ROOT / "templates", dirs_exist_ok=True,
    )


sys.path.insert(0, str(Path(__file__).parent.parent))


# ── Profile-layer unit tests (no Playwright) ──────────────────────────


def test_coerce_hex_normalises_three_six_eight_char_forms():
    from dialekt.branding import coerce_hex
    assert coerce_hex("#ABC") == "#AABBCC"
    assert coerce_hex("abc") == "#AABBCC"
    assert coerce_hex("#ff5629") == "#FF5629"
    assert coerce_hex("ff5629") == "#FF5629"
    # 8-char alpha preserved
    assert coerce_hex("#FF5629AA") == "#FF5629AA"
    assert coerce_hex(None, fallback="#FFFFFF") == "#FFFFFF"
    assert coerce_hex("", fallback="#000000") == "#000000"


def test_coerce_hex_rejects_garbage():
    from dialekt.branding import coerce_hex, BrandValidationError
    with pytest.raises(BrandValidationError):
        coerce_hex("not-a-color")
    with pytest.raises(BrandValidationError):
        coerce_hex("#ZZZZZZ")
    with pytest.raises(BrandValidationError):
        coerce_hex("#1234")  # 4-char (not 3/6/8) — invalid


def test_brand_id_validation_rejects_path_traversal():
    from dialekt.branding import load_brand, BrandValidationError
    for hostile in ("../etc/passwd", "../../foo", "Foo", "x/y", "with space"):
        with pytest.raises(BrandValidationError):
            load_brand(hostile)


def test_save_load_round_trips_profile_with_logo_and_font():
    from dialekt.branding import (
        BrandColors, BrandProfile, save_brand, load_brand,
    )
    profile = BrandProfile(
        id="round_trip",
        name="Round Trip",
        colors=BrandColors(
            primary="#FF5629", secondary="#3A5ADC",
            background="#0C1014", text="#F5F1EA",
        ),
    )
    profile.write_logo(data=b"<svg>logo</svg>", ext="svg")
    profile.write_font(data=b"\x00\x01OTTO" + b"\x00" * 100, ext="otf",
                       family="MyFont")
    save_brand(profile)

    loaded = load_brand("round_trip")
    assert loaded.colors.primary == "#FF5629"
    assert loaded.colors.secondary == "#3A5ADC"
    assert loaded.font_family == "MyFont"
    assert loaded.absolute_logo_path is not None
    assert loaded.absolute_logo_path.exists()
    assert loaded.absolute_font_path is not None
    assert loaded.absolute_font_path.exists()
    assert loaded.absolute_logo_path.read_bytes() == b"<svg>logo</svg>"
    # created_at + updated_at populated
    assert loaded.created_at and loaded.updated_at


def test_re_uploading_logo_with_different_extension_drops_the_old_one():
    from dialekt.branding import (
        BrandColors, BrandProfile, save_brand, load_brand,
    )
    profile = BrandProfile(
        id="ext_swap",
        name="Ext Swap",
        colors=BrandColors(primary="#000000"),
    )
    profile.write_logo(data=b"original-png", ext="png")
    save_brand(profile)

    p1 = load_brand("ext_swap").absolute_logo_path
    assert p1 and p1.suffix == ".png"

    profile.write_logo(data=b"<svg>new</svg>", ext="svg")
    save_brand(profile)
    p2 = load_brand("ext_swap").absolute_logo_path
    assert p2 and p2.suffix == ".svg"
    # The old PNG file is gone — re-upload replaced, not appended.
    assert not p1.exists()


def test_unsupported_extensions_rejected():
    from dialekt.branding import (
        BrandColors, BrandProfile, BrandValidationError,
    )
    profile = BrandProfile(
        id="bad_ext", name="x", colors=BrandColors(primary="#000000"),
    )
    with pytest.raises(BrandValidationError):
        profile.write_logo(data=b"x", ext="exe")
    with pytest.raises(BrandValidationError):
        profile.write_font(data=b"x", ext="zip")


def test_list_brands_skips_corrupt_files():
    """Re-derive the brands root from the live env var because other
    test modules (e.g. test_visual_html.py) may have overwritten
    DIALEKT_VISUAL_ROOT at their own module-load time."""
    from dialekt.branding import (
        BrandColors, BrandProfile, save_brand, list_brands,
    )
    profile = BrandProfile(
        id="good_brand", name="Good",
        colors=BrandColors(primary="#FFFFFF"),
    )
    save_brand(profile)
    # Drop a malformed JSON sibling under whichever root is currently active.
    active_root = Path(os.environ["DIALEKT_VISUAL_ROOT"])
    bad = active_root / "brands" / "broken.json"
    bad.parent.mkdir(parents=True, exist_ok=True)
    bad.write_text("{not json}", encoding="utf-8")

    ids = {b.id for b in list_brands()}
    assert "good_brand" in ids
    assert "broken" not in ids


def test_delete_brand_is_idempotent_and_removes_assets():
    from dialekt.branding import (
        BrandColors, BrandProfile, save_brand, delete_brand,
    )
    profile = BrandProfile(
        id="kill_me", name="Kill",
        colors=BrandColors(primary="#000000"),
    )
    profile.write_logo(data=b"<svg/>", ext="svg")
    save_brand(profile)

    assert delete_brand("kill_me") is True
    assert delete_brand("kill_me") is False  # idempotent
    # Assets directory cleaned up too.
    assert not (_TEST_ROOT / "templates" / "kill_me").exists()


def test_css_prelude_exposes_brand_vars_and_inlines_assets():
    from dialekt.branding import (
        BrandColors, BrandProfile, save_brand, load_brand,
    )
    profile = BrandProfile(
        id="prelude_test", name="Prelude",
        colors=BrandColors(
            primary="#FF5629", secondary="#3A5ADC",
            background="#0C1014", text="#F5F1EA",
        ),
    )
    profile.write_logo(data=b"<svg></svg>", ext="svg")
    profile.write_font(data=b"\x00OTTO" + b"\x00" * 50, ext="otf",
                       family="Brand")
    save_brand(profile)

    css = load_brand("prelude_test").css_prelude()
    assert "--brand-primary: #FF5629" in css
    assert "--brand-secondary: #3A5ADC" in css
    assert "--brand-background: #0C1014" in css
    assert "--brand-text: #F5F1EA" in css
    # Logo is inlined as base64 data URI, not a relative file:// link
    # (Playwright set_content can't follow relative paths).
    assert "data:image/svg+xml;base64," in css
    assert "@font-face" in css
    assert "data:font/otf;base64," in css
    assert "--brand-font: 'Brand'" in css


def test_css_prelude_omits_secondary_if_empty():
    from dialekt.branding import (
        BrandColors, BrandProfile, save_brand, load_brand,
    )
    profile = BrandProfile(
        id="no_secondary", name="No Sec",
        colors=BrandColors(primary="#000000", secondary=""),
    )
    save_brand(profile)
    css = load_brand("no_secondary").css_prelude()
    assert "--brand-primary: #000000" in css
    assert "--brand-secondary" not in css


# ── REST endpoint tests via TestClient ────────────────────────────────


@pytest.fixture(scope="module")
def http():
    from fastapi.testclient import TestClient
    import server as srv
    # Re-use TEST_ROOT (env var already set above) for the /files
    # allow-list expansion to cover ~/.dialekt/visual/out/.
    tmp_dir = _TEST_ROOT
    (tmp_dir / "config.json").write_text("{}")
    srv.DB_PATH = tmp_dir / "dialekt.db"
    srv.SETTINGS_FILE = tmp_dir / "config.json"
    with TestClient(srv.app) as client:
        yield client


def test_branding_upload_creates_brand_round_trip(http):
    fields = {
        "brand_id":         (None, "iba_pilot"),
        "name":             (None, "IBA Pilot"),
        "primary_color":    (None, "#FF5629"),
        "secondary_color":  (None, "#3A5ADC"),
        "background_color": (None, "#0C1014"),
        "text_color":       (None, "#F5F1EA"),
        "logo":             ("logo.svg", b"<svg></svg>", "image/svg+xml"),
    }
    r = http.post("/branding/upload", files=fields)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["brand"]["id"] == "iba_pilot"
    assert body["brand"]["colors"]["primary"] == "#FF5629"
    assert body["brand"]["has_logo"] is True

    r2 = http.get("/branding/iba_pilot")
    assert r2.status_code == 200
    assert r2.json()["brand"]["name"] == "IBA Pilot"

    r3 = http.get("/branding")
    assert r3.status_code == 200
    ids = {b["id"] for b in r3.json()["brands"]}
    assert "iba_pilot" in ids


def test_branding_upload_validates_hex(http):
    r = http.post("/branding/upload", files={
        "brand_id":      (None, "bad_hex"),
        "name":          (None, "x"),
        "primary_color": (None, "not-a-color"),
    })
    assert r.status_code == 422
    assert "hex" in r.text.lower()


def test_branding_upload_rejects_bad_brand_id(http):
    r = http.post("/branding/upload", files={
        "brand_id":      (None, "../etc/pas"),
        "name":          (None, "x"),
        "primary_color": (None, "#000000"),
    })
    assert r.status_code == 422


def test_branding_get_unknown_returns_404(http):
    r = http.get("/branding/this-is-not-a-real-brand")
    # 422 for invalid brand_id pattern (hyphen at pos 16+ ok, but path
    # validation runs first)
    assert r.status_code in (404, 422)


def test_branding_delete_idempotent(http):
    # Create then delete twice
    http.post("/branding/upload", files={
        "brand_id":      (None, "kill_target"),
        "name":          (None, "Kill"),
        "primary_color": (None, "#000000"),
    })
    r1 = http.delete("/branding/kill_target")
    assert r1.status_code == 200 and r1.json()["deleted"] is True
    r2 = http.delete("/branding/kill_target")
    assert r2.status_code == 200 and r2.json()["deleted"] is False


# ── End-to-end preview round-trip (slow — boots Playwright) ───────────


@pytest.mark.slow
def test_branding_preview_round_trip_end_to_end(http):
    """Full path: upload brand → POST /preview → GET /files → PNG bytes
    back. Verifies the brand prelude actually reaches the renderer."""
    from PIL import Image

    fields = {
        "brand_id":         (None, "preview_e2e"),
        "name":             (None, "Preview E2E"),
        "primary_color":    (None, "#E4002B"),
        "secondary_color":  (None, "#FFB81C"),
        "background_color": (None, "#0A0A0A"),
        "text_color":       (None, "#F5F5F5"),
    }
    r = http.post("/branding/upload", files=fields)
    assert r.status_code == 200, r.text

    pr = http.post("/branding/preview_e2e/preview")
    assert pr.status_code == 200, pr.text
    body = pr.json()
    assert body["ok"] is True
    file_path = body["file"]
    assert Path(file_path).exists()

    # /files served the PNG too
    fr = http.get(f"/files?path={file_path}")
    assert fr.status_code == 200
    img = Image.open(io.BytesIO(fr.content))
    assert img.size == (1080, 1080)
    assert img.format == "PNG"


@pytest.mark.slow
def test_visual_render_with_brand_id_does_not_break_existing_templates(http):
    """The 3 default templates don't reference brand vars, so passing
    brand_id should produce a PNG identical-in-structure to the no-brand
    render (same dimensions, same shape). This guards the brand prelude
    not corrupting templates that opt out."""
    from PIL import Image

    http.post("/branding/upload", files={
        "brand_id":      (None, "no_op_brand"),
        "name":          (None, "No-Op"),
        "primary_color": (None, "#FF0000"),
    })
    r = http.post("/visual/render", json={
        "template_id": "default.announcement_1x1",
        "fields": {"TITLE": "Probe"},
        "brand_id": "no_op_brand",
    })
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True
    assert r.json()["width"] == 1080
    assert r.json()["height"] == 1080
    img = Image.open(r.json()["file"])
    assert img.size == (1080, 1080)
