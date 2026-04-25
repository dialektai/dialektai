"""Fetch latest GitHub Release artifacts for dialekt and cache them.

Used by email templates (verify_email, license_activated) to embed
platform-specific download URLs so the user gets the install ZIP/DMG/EXE
delivered with their trial key in one email.

In-memory cache with 1h TTL — keeps GitHub API rate-limit headroom and
avoids blocking signup on a flaky upstream.
"""
from __future__ import annotations

import asyncio
import logging
import re
import time

import httpx

logger = logging.getLogger(__name__)

# Repo coords. Override via env if you fork or rename.
import os as _os
GITHUB_REPO = _os.environ.get("DIALEKT_GITHUB_REPO", "dialektai/dialekt")
GITHUB_API = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
RELEASES_PAGE = f"https://github.com/{GITHUB_REPO}/releases/latest"

_CACHE_TTL_SECONDS = 3600  # 1h
_cache: dict = {"at": 0, "data": None}
_lock = asyncio.Lock()


# Asset name patterns. Order matters — first match wins per platform.
_PATTERNS = {
    "linux_deb":     re.compile(r"\.deb$",          re.I),
    "linux_app":     re.compile(r"\.AppImage$",     re.I),
    "macos_dmg":     re.compile(r"\.dmg$",          re.I),
    "windows_exe":   re.compile(r"-setup\.exe$|installer\.exe$|\.exe$", re.I),
    "windows_msi":   re.compile(r"\.msi$",          re.I),
}


async def get_latest_releases(force: bool = False) -> dict:
    """Return a dict of download URLs by platform key, plus version + page URL.

    Shape:
        {
          "version": "v0.21.0",
          "published_at": "2026-04-25T12:34:56Z",
          "page_url": "https://github.com/.../releases/latest",
          "linux_deb": "...",
          "linux_app": "...",
          "macos_dmg": "...",
          "windows_exe": "...",
          "windows_msi": "...",
        }

    Missing assets simply omit their key (templates handle absence).
    """
    now = time.time()
    if not force and _cache["data"] and (now - _cache["at"]) < _CACHE_TTL_SECONDS:
        return _cache["data"]

    async with _lock:
        # Re-check after acquiring lock (another coroutine may have refreshed)
        if not force and _cache["data"] and (time.time() - _cache["at"]) < _CACHE_TTL_SECONDS:
            return _cache["data"]
        try:
            async with httpx.AsyncClient(timeout=8) as c:
                r = await c.get(GITHUB_API, headers={"Accept": "application/vnd.github+json"})
                r.raise_for_status()
                payload = r.json()
            data = {
                "version": payload.get("tag_name", "latest"),
                "published_at": payload.get("published_at"),
                "page_url": payload.get("html_url", RELEASES_PAGE),
            }
            for asset in payload.get("assets", []):
                name = asset.get("name", "")
                url = asset.get("browser_download_url")
                if not url:
                    continue
                for key, pat in _PATTERNS.items():
                    if key not in data and pat.search(name):
                        data[key] = url
                        break
            _cache["data"] = data
            _cache["at"] = time.time()
            return data
        except Exception as exc:
            logger.warning("releases: GitHub fetch failed: %s; using fallback", exc)
            # Graceful degrade — point users at the releases page where
            # they can pick the right asset themselves.
            fallback = {
                "version": "latest",
                "page_url": RELEASES_PAGE,
            }
            # Cache the fallback briefly too, so we don't hammer GitHub on
            # repeat failures. Shorter TTL so a real release recovers fast.
            _cache["data"] = fallback
            _cache["at"] = time.time() - (_CACHE_TTL_SECONDS - 300)
            return fallback


def releases_summary(releases: dict) -> dict:
    """Email-template friendly view: per-platform tuples (label, url).

    Returns a list of dicts so Jinja can iterate cleanly.
    """
    out = []
    if releases.get("macos_dmg"):
        out.append({"platform": "macOS", "label": "Download for macOS", "url": releases["macos_dmg"], "ext": ".dmg"})
    if releases.get("windows_exe"):
        out.append({"platform": "Windows", "label": "Download for Windows", "url": releases["windows_exe"], "ext": ".exe"})
    if releases.get("linux_deb"):
        out.append({"platform": "Linux (deb)", "label": "Download .deb", "url": releases["linux_deb"], "ext": ".deb"})
    if releases.get("linux_app"):
        out.append({"platform": "Linux (AppImage)", "label": "Download AppImage", "url": releases["linux_app"], "ext": ".AppImage"})
    return out
