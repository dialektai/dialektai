"""First-run installer for the bundled visual template set.

The MCP visual tools and the Settings UI both read templates from
``VISUAL_ROOT/templates/<set>/<template>/``. On a fresh install
that directory is empty — the templates ship inside the dialekt
package itself at ``python/dialekt/tools/visual/_install/`` and
get copied to the user's home on first server boot.

Behaviour:

- ``install_bundled_templates()`` is idempotent. Existing
  user-modified templates are NOT overwritten — the installer
  only fills in template directories that don't yet exist on the
  user's side. This lets a pilot tweak the bundled templates
  in-place without losing edits on every restart.
- A new template added to the bundle in a later release lands in
  the user's home automatically (the per-template skip is keyed
  on the destination directory, not a top-level marker file).
- The installer logs what it copied so first-run boots leave a
  breadcrumb when something is unexpectedly missing.

Tests cover the empty-home, partial-overlay, and locked-template
paths.
"""
from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Iterable

from .template_registry import VISUAL_ROOT

log = logging.getLogger("dialekt.tools.visual.installer")


# Bundled assets ship next to this module so PyInstaller picks them
# up automatically (no separate datas= entry needed in the spec).
BUNDLED_ROOT = Path(__file__).parent / "_install"


def _iter_bundled_sets(bundled_root: Path) -> Iterable[Path]:
    if not bundled_root.exists():
        return []
    return [p for p in bundled_root.iterdir() if p.is_dir()]


def _iter_bundled_templates(set_dir: Path) -> Iterable[Path]:
    return [p for p in set_dir.iterdir() if p.is_dir()]


def install_bundled_templates(
    *,
    target_root: Path | None = None,
    bundled_root: Path | None = None,
) -> dict:
    """Copy any missing bundled templates into the user's
    ``VISUAL_ROOT/templates/`` tree.

    Returns ``{installed: [<template_id>, ...], skipped: [...]}`` for
    test introspection. Never raises on per-template errors — a
    broken bundle should not block server boot. Errors are logged.
    """
    target_root = target_root or (VISUAL_ROOT / "templates")
    bundled_root = bundled_root or BUNDLED_ROOT

    installed: list[str] = []
    skipped: list[str] = []

    if not bundled_root.exists():
        log.warning("visual installer: bundled root missing at %s", bundled_root)
        return {"installed": installed, "skipped": skipped}

    target_root.mkdir(parents=True, exist_ok=True)

    for set_dir in _iter_bundled_sets(bundled_root):
        target_set = target_root / set_dir.name
        target_set.mkdir(parents=True, exist_ok=True)
        for tmpl_dir in _iter_bundled_templates(set_dir):
            template_id = f"{set_dir.name}.{tmpl_dir.name}"
            destination = target_set / tmpl_dir.name
            if destination.exists():
                skipped.append(template_id)
                continue
            try:
                shutil.copytree(tmpl_dir, destination)
                installed.append(template_id)
                log.info("visual installer: installed %s → %s", template_id, destination)
            except OSError as e:
                log.error(
                    "visual installer: failed to copy %s → %s: %s",
                    template_id, destination, e,
                )
    return {"installed": installed, "skipped": skipped}
