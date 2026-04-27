#!/usr/bin/env python3
"""Update landing/changelog.html with a new release entry.

Usage:
    update_changelog.py <version> [<prev_tag>]

    version:  the new release tag, e.g. v0.27.0
    prev_tag: previous release tag, e.g. v0.26.12.
              Default: `git describe --tags --abbrev=0 <version>^`.

Idempotent: if the version block already exists in changelog.html, exits 0
without writing. Designed to be called from .github/workflows/release.yml
after a tag push, but works as a standalone backfill tool too.
"""
from __future__ import annotations

import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CHANGELOG = REPO_ROOT / "landing" / "changelog.html"

CATEGORY_BY_PREFIX = {
    "feat": "Added",
    "fix": "Fixed",
}


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], text=True).strip()


def commits_between(prev: str, version: str) -> list[str]:
    if not prev:
        return []
    log = git("log", f"{prev}..{version}", "--pretty=format:%s", "--no-merges")
    return [line for line in log.splitlines() if line.strip()]


def categorize(commits: list[str]) -> dict[str, list[str]]:
    cats: dict[str, list[str]] = {"Added": [], "Changed": [], "Fixed": []}
    pattern = re.compile(r"^([a-z]+)(\([^)]*\))?:\s*(.+)$")
    for msg in commits:
        m = pattern.match(msg)
        if not m:
            cats["Changed"].append(msg)
            continue
        prefix, _scope, desc = m.groups()
        bucket = CATEGORY_BY_PREFIX.get(prefix, "Changed")
        cats[bucket].append(desc)
    return cats


def severity_tag(version: str) -> str:
    """v0.X.0 → MAJOR; v0.X.Y (Y>0) → PATCH."""
    m = re.match(r"v?\d+\.(\d+)\.(\d+)", version)
    if not m:
        return "MINOR"
    _minor, patch = m.groups()
    return "MAJOR" if patch == "0" else "PATCH"


def html_escape(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def render_block(version: str, commits: list[str]) -> str:
    cats = categorize(commits)
    today = datetime.now(timezone.utc).strftime("%d %b %Y").upper()
    sev = severity_tag(version)
    sev_class = sev.lower()

    m = re.match(r"v?(\d+\.\d+)\.(\d+)", version)
    if not m:
        raise ValueError(f"unrecognized version: {version}")
    base, patch = m.groups()
    version_html = f'v{base}<span class="major">.{patch}</span>'
    bare_version = version.lstrip("v")

    lines = [
        '      <article class="release">',
        '        <div class="release-head">',
        f'          <span class="release-version">{version_html}</span>',
        f'          <span class="release-date">{today}</span>',
        f'          <span class="release-tag {sev_class}">{sev}</span>',
        '        </div>',
        '        <p class="release-summary">'
        f'Released {today}. See '
        f'<a href="https://github.com/dialektai/dialektai/releases/tag/v{bare_version}" '
        'style="color:var(--cyan)">GitHub Release</a> for binaries.</p>',
    ]

    for label in ("Added", "Changed", "Fixed"):
        items = cats[label]
        if not items:
            continue
        lines.append(f'        <h3>{label}</h3>')
        lines.append('        <ul>')
        for item in items:
            lines.append(f'          <li>{html_escape(item)}</li>')
        lines.append('        </ul>')

    lines.append('      </article>')
    lines.append('')
    return "\n".join(lines) + "\n"


def already_present(html: str, version: str) -> bool:
    bare = version.lstrip("v")
    m = re.match(r"(\d+\.\d+)\.(\d+)", bare)
    if not m:
        return False
    base, patch = m.groups()
    needle = re.escape(f'release-version">v{base}<span class="major">.{patch}</span>')
    return re.search(needle, html) is not None


def insert(version: str, block: str) -> bool:
    html = CHANGELOG.read_text()
    if already_present(html, version):
        print(f"v{version.lstrip('v')} already in {CHANGELOG.name}, skipping")
        return False

    marker = '      <article class="release">'
    idx = html.find(marker)
    if idx < 0:
        sys.stderr.write(f"could not find <article class='release'> in {CHANGELOG}\n")
        return False

    CHANGELOG.write_text(html[:idx] + block + html[idx:])
    return True


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        sys.stderr.write(__doc__)
        return 2
    version = argv[1]
    prev = argv[2] if len(argv) > 2 else ""
    if not prev:
        try:
            prev = git("describe", "--tags", "--abbrev=0", f"{version}^")
        except subprocess.CalledProcessError:
            prev = ""

    commits = commits_between(prev, version) if prev else []
    block = render_block(version, commits)

    if insert(version, block):
        n = sum(len(v) for v in categorize(commits).values()) if commits else 0
        print(f"inserted {version}: {n} commits (prev={prev or 'none'})")
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
