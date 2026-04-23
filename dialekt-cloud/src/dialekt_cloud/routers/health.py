"""Health endpoint — used by desktop apps to pick a reachable cloud URL and
by Cloudflare / load-balancers to gate traffic. Intentionally does no DB
or SMTP probing so a burning backend can still report liveness."""
import os
import time

from fastapi import APIRouter

router = APIRouter(tags=["health"])

_BOOT_TIME = time.time()
_VERSION = os.environ.get("DIALEKT_CLOUD_VERSION", "0.9.0")


@router.get("/health")
async def health():
    return {
        "status": "ok",
        "service": "dialekt-cloud",
        "version": _VERSION,
        "uptime_seconds": int(time.time() - _BOOT_TIME),
    }
