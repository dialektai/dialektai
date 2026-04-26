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
GITHUB_REPO = _os.environ.get("DIALEKT_GITHUB_REPO", "dialektai/dialektai")
GITHUB_API = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
RELEASES_PAGE = f"https://github.com/{GITHUB_REPO}/releases/latest"

_CACHE_TTL_SECONDS = 3600  # 1h
_cache: dict = {"at": 0, "data": None}
_lock = asyncio.Lock()


# Asset name patterns — keyed by (platform, arch). The release workflow
# names files like dialekt_<ver>_<arch>.<ext>:
#   linux .deb / .AppImage    →  amd64 | arm64
#   macOS .dmg                →  aarch64 | x86_64
#   windows installers        →  x64 | arm64
# First match wins per key, so per-arch keys never collide.
_PATTERNS = {
    "linux_deb_x86_64":   re.compile(r"_amd64\.deb$",        re.I),
    "linux_deb_arm64":    re.compile(r"_arm64\.deb$",        re.I),
    "linux_app_x86_64":   re.compile(r"_amd64\.AppImage$",   re.I),
    "linux_app_arm64":    re.compile(r"_arm64\.AppImage$",   re.I),
    "macos_dmg_arm64":    re.compile(r"_aarch64\.dmg$",      re.I),
    "macos_dmg_x86_64":   re.compile(r"_x86_64\.dmg$",       re.I),
    "windows_exe_x64":    re.compile(r"_x64-setup\.exe$",    re.I),
    "windows_exe_arm64":  re.compile(r"_arm64-setup\.exe$",  re.I),
    "windows_msi_x64":    re.compile(r"_x64\.msi$",          re.I),
    "windows_msi_arm64":  re.compile(r"_arm64\.msi$",        re.I),
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


def releases_summary(releases: dict) -> list:
    """Email-template friendly view: one row per (platform, arch) asset.

    Returns a list of dicts so Jinja can iterate cleanly. Order is
    macOS → Windows → Linux, ARM64 within each OS rendered alongside
    x86_64 so users can pick what matches their hardware.
    """
    out = []
    if releases.get("macos_dmg_arm64"):
        out.append({"platform": "macOS (Apple Silicon)", "label": "Download .dmg", "url": releases["macos_dmg_arm64"], "ext": ".dmg"})
    if releases.get("macos_dmg_x86_64"):
        out.append({"platform": "macOS (Intel)", "label": "Download .dmg", "url": releases["macos_dmg_x86_64"], "ext": ".dmg"})
    if releases.get("windows_exe_x64"):
        out.append({"platform": "Windows x64", "label": "Download installer", "url": releases["windows_exe_x64"], "ext": ".exe"})
    if releases.get("windows_exe_arm64"):
        out.append({"platform": "Windows ARM64", "label": "Download installer", "url": releases["windows_exe_arm64"], "ext": ".exe"})
    if releases.get("linux_deb_x86_64"):
        out.append({"platform": "Linux x86_64 (.deb)", "label": "Download .deb", "url": releases["linux_deb_x86_64"], "ext": ".deb"})
    if releases.get("linux_deb_arm64"):
        out.append({"platform": "Linux ARM64 (.deb)", "label": "Download .deb", "url": releases["linux_deb_arm64"], "ext": ".deb"})
    if releases.get("linux_app_x86_64"):
        out.append({"platform": "Linux x86_64 (AppImage)", "label": "Download AppImage", "url": releases["linux_app_x86_64"], "ext": ".AppImage"})
    if releases.get("linux_app_arm64"):
        out.append({"platform": "Linux ARM64 (AppImage)", "label": "Download AppImage", "url": releases["linux_app_arm64"], "ext": ".AppImage"})
    return out
