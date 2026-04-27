"""Background tasks managed by the FastAPI lifespan.

Today: trial-expiring reminders (T-7, T-3, T-1, T+0). Single hourly tick.
Add more loops here as we get more lifecycle emails — keep the pattern of
``while not stop: await sleep_until_next_tick(); do_one_pass()`` so the
scheduler is restartable and doesn't lock up if a single pass throws.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


# Days-left thresholds that trigger an email. Each maps to a milestone tag
# stored in ``tenants.expiring_notices_sent`` so we don't double-send.
EXPIRING_MILESTONES = [
    (7, "d7"),
    (3, "d3"),
    (1, "d1"),
    (0, "d0"),  # already expired, send the "your trial ended" mail once
]
TICK_SECONDS = 3600  # one hour


async def run_lifecycle_scheduler(app):
    """Long-running coroutine spawned by the lifespan. Cancelled on shutdown."""
    logger.info("lifecycle scheduler: started")
    try:
        # First pass on startup so we don't have to wait an hour after
        # deploy to send any due reminders.
        await _safe_pass(app)
        while True:
            await asyncio.sleep(TICK_SECONDS)
            await _safe_pass(app)
    except asyncio.CancelledError:
        logger.info("lifecycle scheduler: cancelled")
        raise


async def _safe_pass(app):
    try:
        await _expiring_trials_pass(app)
    except Exception as exc:  # never let a bad pass kill the loop
        logger.exception("lifecycle scheduler pass failed: %s", exc)


async def _expiring_trials_pass(app) -> int:
    """Send trial-expiring emails for tenants that hit a milestone window
    and haven't been notified yet. Returns count of emails sent."""
    pool = app.state.pool
    email_svc = app.state.email
    from ..config import settings

    sent = 0
    now = datetime.now(timezone.utc)
    async with pool.acquire() as conn:
        # Pull all trial tenants with an expires_at, plus their license key.
        rows = await conn.fetch(
            """
            SELECT t.id, t.admin_email, t.expires_at, t.expiring_notices_sent,
                   t.status, t.email_verified_at, t.locale,
                   u.full_name,
                   l.license_key
            FROM tenants t
            LEFT JOIN tenant_users u ON u.tenant_id = t.id AND u.email = t.admin_email
            LEFT JOIN licenses l ON l.tenant_id = t.id AND l.active = TRUE
            WHERE t.status = 'trial' AND t.expires_at IS NOT NULL
            """
        )
    for r in rows:
        # Skip tenants that never verified their email — they'd just be
        # noise in the inbox of a typo'd address.
        if r["email_verified_at"] is None:
            continue
        days_left = (r["expires_at"].replace(tzinfo=timezone.utc) - now).total_seconds() / 86400
        sent_set = set(r["expiring_notices_sent"] or [])
        for threshold_days, tag in EXPIRING_MILESTONES:
            # threshold semantics:
            #   d7: send when 6 < days_left ≤ 7
            #   d3: send when 2 < days_left ≤ 3
            #   d1: send when 0 < days_left ≤ 1
            #   d0: send when days_left ≤ 0 (already expired)
            if tag in sent_set:
                continue
            if tag == "d0":
                hit = days_left <= 0
            else:
                hit = (threshold_days - 1) < days_left <= threshold_days
            if not hit:
                continue
            try:
                await email_svc.send_trial_expiring(
                    to=r["admin_email"],
                    full_name=r["full_name"] or r["admin_email"],
                    days_left=max(0, int(round(days_left))),
                    expires_at_human=r["expires_at"].strftime("%d %b %Y"),
                    license_key=r["license_key"] or "",
                    landing_url=settings.LANDING_URL,
                    locale=r["locale"] or "en",
                )
                async with pool.acquire() as conn:
                    await conn.execute(
                        "UPDATE tenants SET expiring_notices_sent = array_append(expiring_notices_sent, $1) WHERE id = $2",
                        tag, r["id"],
                    )
                sent += 1
                logger.info("trial-expiring %s sent to %s (days_left=%.1f)",
                            tag, r["admin_email"], days_left)
            except Exception as exc:
                logger.warning("trial-expiring send failed for %s: %s", r["admin_email"], exc)
    if sent:
        logger.info("lifecycle scheduler: sent %d expiring emails", sent)
    return sent
