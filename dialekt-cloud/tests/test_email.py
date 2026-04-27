"""Tests for EmailService — no DB needed, uses mock SMTP."""
import asyncio
import pytest
import threading
from unittest.mock import AsyncMock, MagicMock, patch

from dialekt_cloud.services.email import EmailService


def _make_service():
    return EmailService(
        host="localhost",
        port=1025,
        user="",
        password="",
        from_addr="test@dias.now",
        use_tls=False,
    )


@pytest.mark.asyncio
async def test_send_invite_renders():
    """send_invite should call send with correct template and context."""
    svc = _make_service()
    calls = []

    async def mock_send(**kwargs):
        calls.append(kwargs)
        return True

    svc.send = mock_send

    result = await svc.send_invite(
        to="user@example.com",
        invite_token="inv_abc123",
        company_name="Acme Corp",
        landing_url="https://dialekt.dias.now",
    )
    assert result is True
    assert len(calls) == 1
    assert calls[0]["template"] == "invite"
    assert "inv_abc123" in str(calls[0]["context"])


@pytest.mark.asyncio
async def test_send_license_activated_renders():
    svc = _make_service()
    calls = []

    async def mock_send(**kwargs):
        calls.append(kwargs)
        return True

    svc.send = mock_send

    result = await svc.send_license_activated(
        to="admin@company.kz",
        license_key="dialekt_abc",
        company_name="Company KZ",
        plan="team",
        seats=5,
        landing_url="https://dialekt.dias.now",
    )
    assert result is True
    assert calls[0]["template"] == "license_activated"
    assert calls[0]["context"]["plan"] == "team"


@pytest.mark.asyncio
async def test_send_welcome_renders():
    svc = _make_service()
    calls = []

    async def mock_send(**kwargs):
        calls.append(kwargs)
        return True

    svc.send = mock_send

    result = await svc.send_welcome(
        to="admin@company.kz",
        company_name="Company KZ",
        landing_url="https://dialekt.dias.now",
    )
    assert result is True
    assert calls[0]["template"] == "welcome"


@pytest.mark.asyncio
async def test_send_failure_returns_false():
    """Failed SMTP should return False, not raise."""
    svc = _make_service()

    with patch("aiosmtplib.send", side_effect=ConnectionRefusedError("no smtp")):
        result = await svc.send(
            to="user@example.com",
            subject="Test",
            template="invite",
            context={
                "invite_token": "inv_x",
                "company_name": "Test",
                "landing_url": "https://x.com",
                "invite_url": "https://x.com/invite/inv_x",
            },
        )
    assert result is False


@pytest.mark.asyncio
async def test_send_missing_template_uses_fallback():
    """Missing .txt template should use subject as fallback, not crash."""
    svc = _make_service()

    with patch("aiosmtplib.send", return_value=None) as mock_smtp:
        result = await svc.send(
            to="user@example.com",
            subject="Test Subject",
            template="welcome",
            context={"company_name": "ACME", "landing_url": "https://x.com"},
        )
    assert result is True
