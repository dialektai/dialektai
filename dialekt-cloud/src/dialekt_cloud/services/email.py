"""SMTP email service using aiosmtplib + Jinja2 templates."""
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

import aiosmtplib
from jinja2 import Environment, FileSystemLoader

logger = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).parent.parent / "templates" / "emails"


class EmailService:
    def __init__(
        self,
        host: str,
        port: int,
        user: str,
        password: str,
        from_addr: str,
        use_tls: bool = True,
    ):
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.from_addr = from_addr
        self.use_tls = use_tls
        self._env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)), autoescape=True)

    async def send(
        self, *,
        to: str | list[str],
        subject: str,
        template: str,
        context: dict,
        from_addr: str | None = None,
        reply_to: str | None = None,
    ) -> bool:
        """Send a templated email.

        - ``to`` accepts a list to fan out a single send to multiple
          recipients (used for admin-broadcast alerts).
        - ``from_addr`` lets callers pick the right Zoho-alias mailbox per
          email category (security@, billing@, privacy@, hello@). Defaults
          to the instance-level ``self.from_addr`` (hello@) when omitted.
        - ``reply_to`` overrides the inbox a recipient hits when they
          click "Reply" — useful when From is `noreply@` but you still
          want replies to land at hello@.
        """
        try:
            html = self._env.get_template(f"{template}.html").render(**context)
            try:
                text = self._env.get_template(f"{template}.txt").render(**context)
            except Exception:
                text = subject  # fallback plain text

            recipients = [to] if isinstance(to, str) else list(to)

            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = from_addr or self.from_addr
            msg["To"] = ", ".join(recipients)
            if reply_to:
                msg["Reply-To"] = reply_to
            msg.attach(MIMEText(text, "plain", "utf-8"))
            msg.attach(MIMEText(html, "html", "utf-8"))

            smtp_kwargs = dict(
                hostname=self.host,
                port=self.port,
            )
            if self.user:
                smtp_kwargs["username"] = self.user
                smtp_kwargs["password"] = self.password
            # Port 465 = implicit TLS, 587 = STARTTLS, 25 = plain.
            # `use_tls` in the .env controls "encryption expected"; map it to
            # the correct aiosmtplib flag based on port so Gmail (587) works
            # alongside providers that only speak implicit TLS (465).
            if self.use_tls:
                if self.port == 465:
                    smtp_kwargs["use_tls"] = True
                else:
                    smtp_kwargs["start_tls"] = True

            await aiosmtplib.send(msg, recipients=recipients, **smtp_kwargs)
            logger.info("Email sent to %s (template=%s, from=%s)", recipients, template, msg["From"])
            return True
        except Exception as exc:
            logger.error("Failed to send email to %s: %s", to, exc)
            return False

    async def send_invite(self, *, to: str, invite_token: str, company_name: str, landing_url: str) -> bool:
        from ..config import settings as _cfg
        return await self.send(
            to=to,
            subject=f"Приглашение в dialekt.ai — {company_name}",
            template="invite",
            from_addr=_cfg.SMTP_FROM_HELLO,
            context={
                "invite_token": invite_token,
                "company_name": company_name,
                "landing_url": landing_url,
                "invite_url": f"{landing_url}/invite/{invite_token}",
            },
        )

    async def send_license_activated(self, *, to: str, license_key: str, company_name: str, plan: str, seats: int, landing_url: str) -> bool:
        from ..config import settings as _cfg
        return await self.send(
            to=to,
            subject="Ваша лицензия dialekt.ai активирована",
            template="license_activated",
            from_addr=_cfg.SMTP_FROM_HELLO,
            context={
                "license_key": license_key,
                "company_name": company_name,
                "plan": plan,
                "seats": seats,
                "landing_url": landing_url,
            },
        )

    async def send_welcome(self, *, to: str, company_name: str, landing_url: str) -> bool:
        from ..config import settings as _cfg
        return await self.send(
            to=to,
            subject=f"Добро пожаловать в dialekt.ai",
            template="welcome",
            from_addr=_cfg.SMTP_FROM_HELLO,
            context={"company_name": company_name, "landing_url": landing_url},
        )

    # ── Trial lifecycle ─────────────────────────────────────────────────────

    async def send_trial_expiring(
        self, *, to: str, full_name: str, days_left: int, expires_at_human: str,
        license_key: str, landing_url: str,
    ) -> bool:
        """T-7 / T-3 / T-1 / T+0 reminder. Single template parameterised by
        ``days_left`` (0 means already expired)."""
        from ..config import settings as _cfg
        if days_left <= 0:
            subject = "Your dialekt.ai trial has ended — keep going?"
        elif days_left == 1:
            subject = "1 day left on your dialekt.ai trial"
        else:
            subject = f"{days_left} days left on your dialekt.ai trial"
        return await self.send(
            to=to, subject=subject, template="trial_expiring",
            from_addr=_cfg.SMTP_FROM_HELLO,
            context={
                "full_name": full_name,
                "days_left": days_left,
                "expires_at_human": expires_at_human,
                "license_key": license_key,
                "landing_url": landing_url,
                "expired": days_left <= 0,
            },
        )

    async def send_license_extended(
        self, *, to: str, full_name: str, plan: str, seats_limit: int,
        new_expires_at_human: str, days_added: int, landing_url: str,
    ) -> bool:
        """Sent after admin runs POST /admin/tenants/:id/extend so the
        customer knows they got more time / a comp year."""
        from ..config import settings as _cfg
        return await self.send(
            to=to,
            subject="Your dialekt.ai license has been extended",
            template="license_extended",
            from_addr=_cfg.SMTP_FROM_HELLO,
            context={
                "full_name": full_name,
                "plan": plan,
                "seats_limit": seats_limit,
                "new_expires_at_human": new_expires_at_human,
                "days_added": days_added,
                "landing_url": landing_url,
            },
        )

    # ── Internal admin notifications ────────────────────────────────────────

    async def send_admin_signup_notification(
        self, *, to: str, signup_email: str, full_name: str,
        country: str, intended_use: str, signup_source: str | None,
        ip: str, tenant_id: str,
    ) -> bool:
        """Internal heads-up to the founder when a new trial signup lands.
        Sent FROM hello@ TO admin's inbox (also hello@ unless overridden) —
        gives Dias the lead profile in his inbox without opening the dashboard."""
        from ..config import settings as _cfg
        return await self.send(
            to=to,
            subject=f"[lead] {full_name} from {country} — dialekt.ai trial signup",
            template="admin_signup_notification",
            from_addr=_cfg.SMTP_FROM_HELLO,
            context={
                "signup_email": signup_email,
                "full_name": full_name,
                "country": country,
                "intended_use": intended_use,
                "signup_source": signup_source or "(direct)",
                "ip": ip,
                "tenant_id": tenant_id,
            },
        )

    # ── Admin security alerts ───────────────────────────────────────────────

    async def send_admin_security_alert(
        self, *, to: str | list[str], full_name: str | None, kind: str,
        ip: str, user_agent: str, when_human: str, extra: dict | None = None,
    ) -> bool:
        """Single template parameterised by ``kind``:
            - 'password_changed'
            - 'backup_codes_regenerated'
            - 'account_locked'
            - 'totp_enrolled' (re-enrollment after reset)
        Sent FROM security@dias.now. Recipients can be a list (broadcast)."""
        from ..config import settings as _cfg
        subject_map = {
            "password_changed":          "[security] Your dialekt.ai admin password was changed",
            "backup_codes_regenerated":  "[security] Your dialekt.ai admin backup codes were regenerated",
            "account_locked":            "[security] dialekt.ai admin account locked due to failed logins",
            "totp_enrolled":             "[security] A new authenticator was enrolled on your dialekt.ai admin",
        }
        return await self.send(
            to=to,
            subject=subject_map.get(kind, "[security] dialekt.ai admin event"),
            template="admin_security_alert",
            from_addr=_cfg.SMTP_FROM_SECURITY,
            reply_to=_cfg.SMTP_FROM_SECURITY,
            context={
                "kind": kind,
                "full_name": full_name or "admin",
                "ip": ip,
                "user_agent": user_agent,
                "when_human": when_human,
                "extra": extra or {},
            },
        )
