"""Tests for ``dialekt.tools.visual.installer``."""
from __future__ import annotations

import json
from pathlib import Path

from dialekt.tools.visual.installer import (
    BUNDLED_ROOT,
    install_bundled_templates,
)


def test_bundled_root_exists():
    """The package layout should ship at least one template set."""
    assert BUNDLED_ROOT.exists(), f"missing bundled templates at {BUNDLED_ROOT}"
    sets = [p for p in BUNDLED_ROOT.iterdir() if p.is_dir()]
    assert sets, "bundled templates directory is empty"


def test_install_into_empty_target_copies_everything(tmp_path):
    target = tmp_path / "templates"
    out = install_bundled_templates(target_root=target)
    # All bundled templates should be in the installed list.
    assert out["skipped"] == []
    assert "default.announcement_1x1" in out["installed"]
    assert "default.news_4x5" in out["installed"]
    assert "default.schedule_9x16" in out["installed"]
    # Files actually copied.
    assert (target / "default" / "announcement_1x1" / "manifest.json").exists()
    assert (target / "default" / "announcement_1x1" / "template.html").exists()


def test_install_is_idempotent(tmp_path):
    target = tmp_path / "templates"
    install_bundled_templates(target_root=target)
    second = install_bundled_templates(target_root=target)
    assert second["installed"] == []
    assert "default.announcement_1x1" in second["skipped"]


def test_install_does_not_overwrite_user_edits(tmp_path):
    target = tmp_path / "templates"
    install_bundled_templates(target_root=target)
    # Pretend the user edited the template manifest.
    edited = target / "default" / "announcement_1x1" / "manifest.json"
    edited.write_text(json.dumps({"name": "edited", "width": 1, "height": 1}))

    install_bundled_templates(target_root=target)
    # Edits survived — installer skipped the existing dir.
    assert json.loads(edited.read_text())["name"] == "edited"


def test_install_adds_only_new_templates(tmp_path):
    """When the user has 1 of 3 bundled templates installed, the
    installer only fills in the missing 2."""
    bundled = tmp_path / "src"
    target = tmp_path / "dst"

    # Build a synthetic bundle of 3 templates.
    for name in ("alpha", "beta", "gamma"):
        d = bundled / "myset" / name
        d.mkdir(parents=True)
        (d / "manifest.json").write_text("{}")
        (d / "template.html").write_text("<x/>")

    # Pre-create 'beta' in the target so the installer should skip it.
    pre_existing = target / "myset" / "beta"
    pre_existing.mkdir(parents=True)
    (pre_existing / "manifest.json").write_text(json.dumps({"name": "user-edited"}))

    out = install_bundled_templates(target_root=target, bundled_root=bundled)
    assert sorted(out["installed"]) == ["myset.alpha", "myset.gamma"]
    assert out["skipped"] == ["myset.beta"]
    # User's pre-existing manifest preserved.
    assert json.loads(
        (target / "myset" / "beta" / "manifest.json").read_text()
    ) == {"name": "user-edited"}


def test_install_handles_missing_bundle_gracefully(tmp_path):
    target = tmp_path / "templates"
    nonexistent = tmp_path / "does-not-exist"
    out = install_bundled_templates(target_root=target, bundled_root=nonexistent)
    assert out == {"installed": [], "skipped": []}


def test_install_handles_missing_target_gracefully(tmp_path):
    # Target doesn't exist yet — installer should create it.
    target = tmp_path / "deep" / "nested" / "templates"
    out = install_bundled_templates(target_root=target)
    assert out["installed"]
    assert target.is_dir()


def test_bundled_templates_have_required_fields():
    """Every template that ships in the bundle must parse as a valid
    manifest the registry can load — caught here before it lands at
    a user's home with a missing field."""
    sets = [p for p in BUNDLED_ROOT.iterdir() if p.is_dir()]
    for set_dir in sets:
        for tmpl_dir in set_dir.iterdir():
            if not tmpl_dir.is_dir():
                continue
            manifest = tmpl_dir / "manifest.json"
            assert manifest.exists(), f"{tmpl_dir.name} missing manifest.json"
            data = json.loads(manifest.read_text(encoding="utf-8"))
            for key in ("width", "height"):
                assert key in data, f"{tmpl_dir.name}: missing {key}"
            html_rel = data.get("html", "template.html")
            assert (tmpl_dir / html_rel).exists(), (
                f"{tmpl_dir.name}: html file missing"
            )
