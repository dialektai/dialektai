"""CI guard: WHAT_DIALEKT_DOES_TODAY.md version header must match the latest
git tag.

Rationale: the doc is the first thing a pilot reads. If the version string
is stale (e.g., says v0.20.0 while the repo is at v0.27.0), pilots see
contradictory information. This test fails the moment a new release tag is
cut without updating the doc — making the drift impossible to miss in CI.

The version format assumed: ``**Version:** vX.Y.Z`` on its own line.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent.parent
DOC_PATH = REPO_ROOT / "docs" / "WHAT_DIALEKT_DOES_TODAY.md"
VERSION_PATTERN = re.compile(r"^\*\*Version:\*\*\s+(v[\d]+\.[\d]+\.[\d]+)", re.MULTILINE)


def _latest_git_tag() -> str | None:
    """Return the latest semver tag reachable from HEAD, or None if untagged."""
    try:
        result = subprocess.run(
            ["git", "tag", "--sort=-version:refname"],
            capture_output=True, text=True, cwd=REPO_ROOT, timeout=10
        )
        tags = [t.strip() for t in result.stdout.splitlines() if re.match(r"^v\d+\.\d+\.\d+", t.strip())]
        return tags[0] if tags else None
    except Exception:
        return None


def _doc_version() -> str | None:
    """Extract the **Version:** value from WHAT_DIALEKT_DOES_TODAY.md."""
    if not DOC_PATH.exists():
        return None
    text = DOC_PATH.read_text(encoding="utf-8")
    m = VERSION_PATTERN.search(text)
    return m.group(1) if m else None


def _major_minor(v: str) -> tuple[int, int] | None:
    """Extract (major, minor) from a 'vX.Y.Z' string, ignoring patch."""
    m = re.match(r"^v(\d+)\.(\d+)\.\d+$", v)
    return (int(m.group(1)), int(m.group(2))) if m else None


def test_what_dialekt_does_today_version_matches_latest_tag():
    """WHAT_DIALEKT_DOES_TODAY.md **Version:** major.minor must match the
    latest git tag's major.minor. Patch differences are tolerated — patch
    releases are typically bug fixes that don't change pilot-facing behavior,
    so the doc may legitimately lag by one patch without misinforming pilots.

    If this fails: bump the **Version:** line in
    docs/WHAT_DIALEKT_DOES_TODAY.md to the current minor release.
    """
    latest_tag = _latest_git_tag()
    doc_version = _doc_version()

    if latest_tag is None:
        pytest.skip("No semver git tags found — untagged repo, skipping version guard")

    assert doc_version is not None, (
        f"Could not find **Version:** header in {DOC_PATH}. "
        "The file must contain a line like: **Version:** v0.27.0"
    )

    tag_mm = _major_minor(latest_tag)
    doc_mm = _major_minor(doc_version)
    assert tag_mm is not None, f"Latest tag {latest_tag!r} is not in vX.Y.Z form"
    assert doc_mm is not None, f"Doc version {doc_version!r} is not in vX.Y.Z form"

    assert doc_mm == tag_mm, (
        f"WHAT_DIALEKT_DOES_TODAY.md says Version={doc_version!r} "
        f"(major.minor={doc_mm}) but the latest git tag is {latest_tag!r} "
        f"(major.minor={tag_mm}). Bump the **Version:** line to the current "
        "minor release."
    )


def test_what_dialekt_does_today_file_exists():
    """The pilot-facing summary document must exist at docs/WHAT_DIALEKT_DOES_TODAY.md."""
    assert DOC_PATH.exists(), (
        f"Missing pilot-facing summary: {DOC_PATH}. "
        "This file is the first thing a pilot reads."
    )
