"""Route a scheduled run's output to the manifest-declared destination.

Manifests carry an ``output.destination`` block; this module turns
that declarative spec into a concrete delivery action. Three kinds:

- ``notification`` — write a row into ``notifications`` so the next
  app open shows it as an unread item. Useful for "the digest is
  ready, look at it when you have time" flows.
- ``email_or_telegram`` — send to a Telegram chat through the
  ``telegram_chat_id`` field (resolved through ``dialekt.secrets`` if
  it's a ``${secrets.*}`` reference). Email path is a stub for now —
  pilots use Telegram first; SMTP is the v0.28 follow-up.
- ``filesystem`` — write the output to a path under the user's home,
  expanding ``{{date}}`` / ``{{time}}`` / ``{{agent_id}}`` placeholders.

Failure isolation: every delivery branch swallows its own exception
and returns a ``DeliveryResult(status="failed", ...)``. The scheduler
must not crash because Telegram is rate-limited or the disk is full —
the run history shows the failure and the user can retry by hand.
"""
from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import aiosqlite
import yaml as _yaml

log = logging.getLogger("dialekt.scheduler.delivery")

# Path-template placeholders the filesystem destination understands.
# Kept tiny on purpose — anything richer should live in a manifest
# variable, not a free-form template language.
_PATH_VARS = ("date", "time", "datetime", "agent_id", "run_id")

_SECRET_REF_RE = re.compile(r"\$\{secrets\.([a-zA-Z0-9_]+)\}")


@dataclass
class DeliveryResult:
    status: str            # "sent" | "skipped" | "failed"
    detail: str | None     # human-readable, ends up in scheduled_runs.delivery_status_detail
    target: str | None     # path / chat_id / notification id


async def deliver(
    *,
    db: aiosqlite.Connection,
    agent: dict,
    run_id: str,
    output: str,
    triggered_at: datetime,
) -> DeliveryResult:
    """Top-level dispatch. Returns a ``DeliveryResult`` even on failure —
    callers persist it on the ``scheduled_runs`` row.
    """
    destination = _read_destination(agent)
    if not destination:
        return DeliveryResult("skipped", "manifest has no output.destination", None)

    if not output or not output.strip():
        return DeliveryResult("skipped", "agent produced no text output", None)

    kind = (destination.get("type") or "").strip()
    try:
        if kind == "notification":
            return await _deliver_notification(db, agent, run_id, output)
        if kind == "email_or_telegram":
            return await _deliver_telegram(destination, agent, output)
        if kind == "filesystem":
            return await _deliver_filesystem(destination, agent, run_id, output, triggered_at)
        return DeliveryResult("failed", f"unknown destination.type {kind!r}", None)
    except Exception as e:  # noqa: BLE001 — boundary catch
        log.exception("delivery failed for agent %s run %s", agent.get("id"), run_id)
        return DeliveryResult("failed", f"{type(e).__name__}: {e}", None)


# ── per-kind handlers ────────────────────────────────────────────────────────

async def _deliver_notification(
    db: aiosqlite.Connection, agent: dict, run_id: str, output: str,
) -> DeliveryResult:
    """In-app notification surface. The schema is owned by the
    scheduler (it's the only writer right now) — UI later will join
    against agents to render "from <agent name>"."""
    await db.execute(
        "INSERT INTO scheduled_notifications "
        "(run_id, agent_id, body, created_at, read_at) "
        "VALUES (?, ?, ?, datetime('now'), NULL)",
        (run_id, agent.get("id"), output),
    )
    await db.commit()
    return DeliveryResult("sent", "notification stored", run_id)


async def _deliver_telegram(destination: dict, agent: dict, output: str) -> DeliveryResult:
    """Send to Telegram via the user's bot token + chat id.

    Both fields live in the keychain via ``dialekt.secrets``; the
    manifest references them as ``${secrets.<name>}``. We don't ship
    a global dialekt-cloud bot — pilots use their own bot, same model
    as the Instagram publisher.

    Telegram has a 4096-char text limit; longer outputs are split into
    chunks at paragraph boundaries when possible.
    """
    chat_id = _resolve_secret(destination.get("telegram_chat_id"))
    bot_token = _resolve_secret(destination.get("telegram_bot_token") or "${secrets.telegram_bot_token}")
    if not chat_id:
        return DeliveryResult("failed", "telegram_chat_id not configured", None)
    if not bot_token:
        return DeliveryResult("failed", "telegram_bot_token not configured", None)

    import httpx
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    chunks = _chunk_for_telegram(output)
    async with httpx.AsyncClient(timeout=20) as cli:
        for chunk in chunks:
            r = await cli.post(url, json={
                "chat_id": chat_id,
                "text": chunk,
                "disable_web_page_preview": True,
            })
            if r.status_code != 200:
                return DeliveryResult(
                    "failed",
                    f"telegram api {r.status_code}: {r.text[:200]}",
                    str(chat_id),
                )
    return DeliveryResult("sent", f"{len(chunks)} message(s)", str(chat_id))


async def _deliver_filesystem(
    destination: dict, agent: dict, run_id: str, output: str, triggered_at: datetime,
) -> DeliveryResult:
    raw_path = destination.get("path")
    if not raw_path:
        return DeliveryResult("failed", "filesystem destination missing path", None)
    expanded = _expand_path(raw_path, agent_id=agent.get("id") or "", run_id=run_id, when=triggered_at)
    target = Path(os.path.expanduser(expanded))
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(output)
    return DeliveryResult("sent", f"{target.stat().st_size} bytes", str(target))


# ── helpers ──────────────────────────────────────────────────────────────────

def _read_destination(agent: dict) -> dict | None:
    """Pull ``output.destination`` out of the agent's manifest YAML."""
    manifest_yaml = agent.get("manifest_yaml") or ""
    if not manifest_yaml:
        return None
    try:
        data = _yaml.safe_load(manifest_yaml) or {}
    except Exception as e:
        log.warning("agent %s manifest parse failed: %s", agent.get("id"), e)
        return None
    output = data.get("output") or {}
    dest = output.get("destination")
    return dest if isinstance(dest, dict) else None


def _resolve_secret(raw: Any) -> str | None:
    if not raw or not isinstance(raw, str):
        return None
    m = _SECRET_REF_RE.fullmatch(raw.strip())
    if not m:
        return raw
    from dialekt.secrets import get_secret
    return get_secret(m.group(1))


def _expand_path(template: str, *, agent_id: str, run_id: str, when: datetime) -> str:
    repl = {
        "date": when.strftime("%Y-%m-%d"),
        "time": when.strftime("%H-%M-%S"),
        "datetime": when.strftime("%Y-%m-%dT%H-%M-%S"),
        "agent_id": agent_id,
        "run_id": run_id,
    }
    out = template
    for k, v in repl.items():
        out = out.replace(f"{{{{{k}}}}}", v)
    return out


def _chunk_for_telegram(text: str, *, limit: int = 4000) -> list[str]:
    """Split ``text`` into ≤``limit``-char chunks at paragraph or line
    boundaries — Telegram caps a single sendMessage at 4096 chars and
    abrupt mid-word cuts are jarring in practice."""
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    remaining = text
    while len(remaining) > limit:
        cut = remaining.rfind("\n\n", 0, limit)
        if cut < limit // 2:
            cut = remaining.rfind("\n", 0, limit)
        if cut < limit // 2:
            cut = remaining.rfind(" ", 0, limit)
        if cut <= 0:
            cut = limit
        chunks.append(remaining[:cut].rstrip())
        remaining = remaining[cut:].lstrip()
    if remaining:
        chunks.append(remaining)
    return chunks


# Schema for the in-app notifications surface — wired into the main
# server schema in runner.SCHEDULED_RUNS_SCHEMA so a single
# executescript brings up everything the scheduler needs.
NOTIFICATIONS_SCHEMA = """
CREATE TABLE IF NOT EXISTS scheduled_notifications (
    run_id     TEXT PRIMARY KEY,
    agent_id   TEXT NOT NULL,
    body       TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    read_at    TEXT
);

CREATE INDEX IF NOT EXISTS idx_scheduled_notif_agent
    ON scheduled_notifications(agent_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_scheduled_notif_unread
    ON scheduled_notifications(read_at, created_at DESC);
"""
