"""
Background license re-validation for Blocker 3.

Polls the cloud every `REFRESH_INTERVAL_SECONDS` and clears the local
license + bearer token if the cloud reports `valid: false` (tenant
suspended, expired, deleted).

Offline grace period: if the cloud is unreachable for longer than
`OFFLINE_GRACE_SECONDS`, the license is considered revoked locally too.
This closes the "took the laptop to a cafe and kept using a cancelled
subscription" loophole. Clock-skew tolerance: ±5 minutes — we never
treat a fresh successful validation as stale within that window.

Module-level state stored in the `load_settings`/`save_settings` result:
    last_license_validated_at  (float, unix time)
    last_license_revalidation_status  ("ok" | "revoked" | "offline")

Additional helpers:
    refresh_once(load, save)     — do ONE check right now, used for inline
                                   revalidation on user activity.
    start_refresher(load, save)  — long-running asyncio task for periodic checks.
    stop_refresher(task)         — cooperative cancel.
    refresh_if_stale(load, save) — skip if last_validated is within 30 min.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Callable

import httpx

log = logging.getLogger("dialekt.license_refresh")

REFRESH_INTERVAL_SECONDS = 30 * 60   # 30 minutes between background polls
OFFLINE_GRACE_SECONDS = 24 * 60 * 60  # 24 hours without a successful check
STALE_THRESHOLD_SECONDS = 30 * 60    # inline revalidate if older than this
CLOCK_SKEW_SECONDS = 5 * 60          # tolerate ±5 min drift
HTTP_TIMEOUT = 10.0
MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = (1, 3, 8)     # exponential-ish


async def _call_cloud(cloud_url: str, license_key: str) -> dict:
    """POST the license key to the cloud validator. Retries with backoff."""
    url = cloud_url.rstrip("/") + "/auth/validate-license"
    last_err: Exception | None = None
    for attempt, backoff in enumerate(RETRY_BACKOFF_SECONDS[:MAX_RETRIES]):
        try:
            async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
                r = await c.post(url, json={"license_key": license_key})
            if r.status_code == 200:
                return r.json()
            # Cloud reported non-200 but is reachable — treat as negative answer
            return {"valid": False, "reason": f"HTTP {r.status_code}"}
        except (httpx.TimeoutException, httpx.TransportError) as e:
            last_err = e
            if attempt < MAX_RETRIES - 1:
                await asyncio.sleep(backoff)
            continue
        except Exception as e:
            # Don't retry on schema/json errors — it's likely a server bug
            last_err = e
            break
    raise RuntimeError(f"cloud unreachable after {MAX_RETRIES} attempts: {last_err}")


async def refresh_once(load_settings: Callable[[], dict],
                       save_settings: Callable[[dict], None]) -> dict:
    """Do ONE cloud-side validation; mutate settings if revoked. Returns
    a report dict: {status, reason?}."""
    s = load_settings()
    license_key = s.get("license_key")
    if not license_key:
        return {"status": "no-license", "reason": "nothing to validate"}

    cloud_url = s.get("cloud_api_url") or "https://api.dialekt.ai"
    try:
        data = await _call_cloud(cloud_url, license_key)
    except Exception as e:
        # Cloud unreachable — check grace period
        now = time.time()
        last = s.get("last_license_validated_at", 0)
        age = now - last
        if last and age <= OFFLINE_GRACE_SECONDS:
            log.info("license check offline (reachable %.1fh ago, within grace)", age / 3600)
            s["last_license_revalidation_status"] = "offline"
            save_settings(s)
            return {"status": "offline", "reason": str(e), "grace_remaining_hours": round((OFFLINE_GRACE_SECONDS - age) / 3600, 1)}
        # Grace expired OR never had a successful check
        log.warning("license check offline past grace period (age=%.1fh); locking",
                    age / 3600 if last else 99999)
        _revoke_locally(s, save_settings, reason="offline_grace_expired")
        return {"status": "revoked", "reason": "offline grace period exceeded"}

    # Cloud answered — honour its verdict.
    if data.get("valid"):
        now = time.time()
        s["last_license_validated_at"] = now
        s["last_license_revalidation_status"] = "ok"
        # Opportunistic refresh of tenant/bearer if provided.
        if data.get("bearer_token"):
            s["cloud_bearer_token"] = data["bearer_token"]
        # Keep legacy tenant_info shape in sync.
        if "plan" in data or "seats_limit" in data:
            tenant = s.get("tenant_info") or {}
            if data.get("plan"):
                tenant["plan"] = data["plan"]
            if data.get("seats_limit") is not None:
                tenant["seats_limit"] = data["seats_limit"]
            if data.get("expires_at") is not None:
                tenant["expires_at"] = data["expires_at"]
            s["tenant_info"] = tenant
        save_settings(s)
        return {"status": "ok"}

    # Cloud says invalid → revoke.
    reason = data.get("reason") or data.get("message") or "cloud reported invalid"
    _revoke_locally(s, save_settings, reason=str(reason))
    return {"status": "revoked", "reason": reason}


def _revoke_locally(settings_dict: dict,
                    save_settings: Callable[[dict], None],
                    reason: str) -> None:
    """Clear license state in settings AND persist (save_settings routes
    sensitive values to the keychain, so this also deletes them there)."""
    settings_dict["license_key"] = None
    settings_dict["cloud_bearer_token"] = None
    settings_dict["last_license_revalidation_status"] = "revoked"
    settings_dict["last_license_revocation_reason"] = reason
    settings_dict["last_license_revoked_at"] = time.time()
    save_settings(settings_dict)
    log.warning("license revoked locally: %s", reason)


async def refresh_if_stale(load_settings: Callable[[], dict],
                           save_settings: Callable[[dict], None]) -> dict:
    """Inline revalidation: returns fast if last check was < STALE_THRESHOLD
    minutes ago. Otherwise runs one full validation."""
    s = load_settings()
    last = s.get("last_license_validated_at", 0)
    now = time.time()
    if last and (now - last) < STALE_THRESHOLD_SECONDS - CLOCK_SKEW_SECONDS:
        return {"status": "fresh", "age_seconds": now - last}
    return await refresh_once(load_settings, save_settings)


async def start_refresher(load_settings: Callable[[], dict],
                          save_settings: Callable[[dict], None]) -> None:
    """Long-running background coroutine — poll every 30 minutes while the
    app is alive. Never raises; errors are logged."""
    log.info("license refresher started (interval=%ds, grace=%ds)",
             REFRESH_INTERVAL_SECONDS, OFFLINE_GRACE_SECONDS)
    # First tick deferred slightly so app boot isn't blocked on network.
    await asyncio.sleep(30)
    while True:
        try:
            report = await refresh_once(load_settings, save_settings)
            log.debug("background license check: %s", report)
        except Exception as e:
            log.exception("license refresh raised: %s", e)
        try:
            await asyncio.sleep(REFRESH_INTERVAL_SECONDS)
        except asyncio.CancelledError:
            log.info("license refresher cancelled")
            break


async def stop_refresher(task: asyncio.Task | None) -> None:
    if task is None or task.done():
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
