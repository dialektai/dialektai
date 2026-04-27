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


def test_what_dialekt_does_today_version_matches_latest_tag():
    """WHAT_DIALEKT_DOES_TODAY.md **Version:** must match the latest git tag.

    If this fails: update docs/WHAT_DIALEKT_DOES_TODAY.md to reflect the
    new release before merging.
    """
    latest_tag = _latest_git_tag()
    doc_version = _doc_version()

    if latest_tag is None:
        pytest.skip("No semver git tags found — untagged repo, skipping version guard")

    assert doc_version is not None, (
        f"Could not find **Version:** header in {DOC_PATH}. "
        "The file must contain a line like: **Version:** v0.27.0"
    )

    assert doc_version == latest_tag, (
        f"WHAT_DIALEKT_DOES_TODAY.md says Version={doc_version!r} "
        f"but the latest git tag is {latest_tag!r}. "
        "Update the **Version:** line in that doc before merging."
    )


def test_what_dialekt_does_today_file_exists():
    """The pilot-facing summary document must exist at docs/WHAT_DIALEKT_DOES_TODAY.md."""
    assert DOC_PATH.exists(), (
        f"Missing pilot-facing summary: {DOC_PATH}. "
        "This file is the first thing a pilot reads."
    )
