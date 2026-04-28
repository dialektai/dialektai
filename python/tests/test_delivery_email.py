"""Tests for the SMTP / email destination in scheduler.delivery."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

from dialekt.scheduler import delivery as delivery_mod


def _agent(manifest_yaml: str) -> dict:
    return {
        "id": "test-agent",
        "name": "Test Agent",
        "manifest_yaml": manifest_yaml,
    }


def _make_email_manifest(**overrides) -> str:
    fields = {
        "type": "email",
        "smtp_host": "smtp.example.com",
        "smtp_port": "587",
        "smtp_user": "noreply@example.com",
        "smtp_password": "secret-pwd",
        "smtp_from": "noreply@example.com",
        "email_to": "ops@example.com",
        "subject": "{{agent_name}} digest — {{date}}",
    }
    fields.update(overrides)
    lines = ["output:", "  format: \"markdown\"", "  destination:"]
    for k, v in fields.items():
        if isinstance(v, list):
            lines.append(f"    {k}:")
            for item in v:
                lines.append(f"      - \"{item}\"")
        else:
            lines.append(f"    {k}: \"{v}\"")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# happy paths
# ---------------------------------------------------------------------------


def test_email_delivery_sends_message():
    sent_messages: list = []

    async def _stub_send(message, **kwargs):
        sent_messages.append((message, kwargs))

    async def run():
        with patch("aiosmtplib.send", new=_stub_send):
            agent = _agent(_make_email_manifest())
            triggered = datetime(2026, 4, 28, 9, 0, tzinfo=timezone.utc)
            result = await delivery_mod.deliver(
                db=None,  # email path doesn't touch DB
                agent=agent,
                run_id="run-1",
                output="The digest body.",
                triggered_at=triggered,
            )
        assert result.status == "sent"
        assert "ops@example.com" in result.target
        assert sent_messages
        msg, kwargs = sent_messages[0]
        assert msg["To"] == "ops@example.com"
        assert msg["From"] == "noreply@example.com"
        assert "Test Agent" in msg["Subject"]
        assert "2026-04-28" in msg["Subject"]
        assert kwargs["hostname"] == "smtp.example.com"
        assert kwargs["port"] == 587

    asyncio.run(run())


def test_email_supports_multiple_recipients_via_list():
    sent_messages: list = []

    async def _stub_send(message, **kwargs):
        sent_messages.append(message)

    async def run():
        with patch("aiosmtplib.send", new=_stub_send):
            agent = _agent(
                _make_email_manifest(email_to=["a@x.com", "b@x.com"])
            )
            await delivery_mod.deliver(
                db=None, agent=agent, run_id="r",
                output="hi", triggered_at=datetime.now(timezone.utc),
            )
        assert "a@x.com" in sent_messages[0]["To"]
        assert "b@x.com" in sent_messages[0]["To"]

    asyncio.run(run())


def test_email_supports_comma_separated_string():
    sent_messages: list = []

    async def _stub_send(message, **kwargs):
        sent_messages.append(message)

    async def run():
        with patch("aiosmtplib.send", new=_stub_send):
            agent = _agent(_make_email_manifest(email_to="a@x.com, b@x.com"))
            await delivery_mod.deliver(
                db=None, agent=agent, run_id="r",
                output="hi", triggered_at=datetime.now(timezone.utc),
            )
        assert "a@x.com" in sent_messages[0]["To"]
        assert "b@x.com" in sent_messages[0]["To"]

    asyncio.run(run())


# ---------------------------------------------------------------------------
# error paths
# ---------------------------------------------------------------------------


def test_email_missing_credentials():
    async def run():
        agent = _agent(_make_email_manifest(smtp_host=""))
        result = await delivery_mod.deliver(
            db=None, agent=agent, run_id="r",
            output="hi", triggered_at=datetime.now(timezone.utc),
        )
        assert result.status == "failed"
        assert "smtp credentials" in result.detail

    asyncio.run(run())


def test_email_invalid_port():
    async def run():
        agent = _agent(_make_email_manifest(smtp_port="not-a-number"))
        result = await delivery_mod.deliver(
            db=None, agent=agent, run_id="r",
            output="hi", triggered_at=datetime.now(timezone.utc),
        )
        assert result.status == "failed"
        assert "smtp_port" in result.detail

    asyncio.run(run())


def test_email_no_recipients():
    async def run():
        agent = _agent(_make_email_manifest(email_to=""))
        result = await delivery_mod.deliver(
            db=None, agent=agent, run_id="r",
            output="hi", triggered_at=datetime.now(timezone.utc),
        )
        assert result.status == "failed"
        assert "no recipients" in result.detail

    asyncio.run(run())


def test_email_smtp_failure_classified():
    async def _stub_send(message, **kwargs):
        raise RuntimeError("Connection refused")

    async def run():
        with patch("aiosmtplib.send", new=_stub_send):
            agent = _agent(_make_email_manifest())
            result = await delivery_mod.deliver(
                db=None, agent=agent, run_id="r",
                output="hi", triggered_at=datetime.now(timezone.utc),
            )
        assert result.status == "failed"
        assert "smtp send failed" in result.detail
        assert "Connection refused" in result.detail

    asyncio.run(run())
