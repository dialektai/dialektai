"""SMTP email service using aiosmtplib + Jinja2 templates.

Templates live under ``templates/emails/{locale}/{name}.{html,txt}``.
Subject lines live inside each template as ``{% block subject %}...{% endblock %}``
with ``{% autoescape false %}`` so interpolated values don't HTML-escape into
mail headers (e.g. ``Smith & Co`` stays as ``Smith & Co``, not ``Smith &amp; Co``).

If a template is missing in the requested locale, the service falls back to
``en`` so a half-translated rollout never drops a transactional email.
"""
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

import aiosmtplib
from jinja2 import Environment, FileSystemLoader, TemplateNotFound, select_autoescape

logger = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).parent.parent / "templates" / "emails"
SUPPORTED_LOCALES = ("en", "ru")
DEFAULT_LOCALE = "en"


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
        # Autoescape only HTML files. .txt and subject blocks stay raw —
        # subject blocks individually wrap themselves in {% autoescape false %}
        # for headers; .txt is plain text where escaping breaks readability.
        self._env = Environment(
            loader=FileSystemLoader(str(TEMPLATES_DIR)),
            autoescape=select_autoescape(enabled_extensions=("html",)),
        )

    def _resolve(self, locale: str, template: str, ext: str) -> str:
        """Return a Jinja-relative path that exists, falling back to EN."""
        candidate = f"{locale}/{template}.{ext}"
        try:
            self._env.get_template(candidate)
            return candidate
        except TemplateNotFound:
            if locale != DEFAULT_LOCALE:
                fallback = f"{DEFAULT_LOCALE}/{template}.{ext}"
                self._env.get_template(fallback)  # raises if also missing
                logger.info(
                    "email template %s missing for locale=%s; falling back to %s",
                    template, locale, DEFAULT_LOCALE,
                )
                return fallback
            raise

    async def send(
        self, *,
        to: str | list[str],
        template: str,
        context: dict,
        locale: str = DEFAULT_LOCALE,
        subject: str | None = None,
        from_addr: str | None = None,
        reply_to: str | None = None,
    ) -> bool:
        """Send a templated email.

        - ``locale`` picks which ``emails/{locale}/`` folder to read from.
          Falls back to ``en`` if the template is missing in the requested
          locale (logged at INFO).
        - ``subject`` is normally extracted from the template's
          ``{% block subject %}``. Pass it explicitly only for legacy callers
          or one-off overrides.
        - ``to`` accepts a list to fan out a single send to multiple
          recipients (used for admin-broadcast alerts).
        - ``from_addr`` lets callers pick the right alias mailbox per
          email category (security@, billing@, privacy@, hello@). Defaults
          to the instance-level ``self.from_addr`` (hello@) when omitted.
        - ``reply_to`` overrides the inbox a recipient hits when they
          click "Reply".
        """
        if locale not in SUPPORTED_LOCALES:
            logger.warning("unknown locale %r, falling back to %s", locale, DEFAULT_LOCALE)
            locale = DEFAULT_LOCALE

        try:
            html_tpl = self._env.get_template(self._resolve(locale, template, "html"))
            html = html_tpl.render(**context)

            # Subject: prefer caller override, else pull from template block.
            # Children declare {% block subject %}{% autoescape false %}...{%
            # endautoescape %}{% endblock %}, which the layout exposes as the
            # <title> element. Render the block in isolation to get a clean
            # header value (no HTML/whitespace).
            if subject is None:
                if "subject" not in html_tpl.blocks:
                    raise RuntimeError(
                        f"template {template} has no {{% block subject %}} and no subject= passed"
                    )
                block_ctx = html_tpl.new_context(vars=context)
                subject = "".join(html_tpl.blocks["subject"](block_ctx))
            # Strip CR/LF to defend against header injection via interpolated
            # values (e.g. a malicious full_name containing "\nBcc: attacker@").
            subject = subject.replace("\r", " ").replace("\n", " ").strip()

            try:
                text_tpl = self._env.get_template(self._resolve(locale, template, "txt"))
                text = text_tpl.render(**context)
            except TemplateNotFound:
                text = subject  # last-resort plain-text fallback

            recipients = [to] if isinstance(to, str) else list(to)

            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = from_addr or self.from_addr
            msg["To"] = ", ".join(recipients)
            if reply_to:
                msg["Reply-To"] = reply_to
            msg.attach(MIMEText(text, "plain", "utf-8"))
            msg.attach(MIMEText(html, "html", "utf-8"))

            smtp_kwargs = dict(hostname=self.host, port=self.port)
            if self.user:
                smtp_kwargs["username"] = self.user
                smtp_kwargs["password"] = self.password
            # Port 465 = implicit TLS, 587 = STARTTLS, 25 = plain.
            if self.use_tls:
                if self.port == 465:
                    smtp_kwargs["use_tls"] = True
                else:
                    smtp_kwargs["start_tls"] = True

            await aiosmtplib.send(msg, recipients=recipients, **smtp_kwargs)
            logger.info(
                "Email sent to %s (template=%s, locale=%s, from=%s)",
                recipients, template, locale, msg["From"],
            )
            return True
        except Exception as exc:
            logger.error("Failed to send email to %s: %s", to, exc)
            return False

    async def send_invite(
        self, *, to: str, invite_token: str, company_name: str,
        landing_url: str, locale: str = DEFAULT_LOCALE,
    ) -> bool:
        from ..config import settings as _cfg
        return await self.send(
            to=to,
            template="invite",
            locale=locale,
            from_addr=_cfg.SMTP_FROM_HELLO,
            context={
                "invite_token": invite_token,
                "company_name": company_name,
                "landing_url": landing_url,
                "invite_url": f"{landing_url}/invite/{invite_token}",
            },
        )

    async def send_license_activated(
        self, *, to: str, license_key: str, company_name: str,
        plan: str, seats: int, landing_url: str,
        locale: str = DEFAULT_LOCALE,
    ) -> bool:
        from ..config import settings as _cfg
        return await self.send(
            to=to,
            template="license_activated",
            locale=locale,
            from_addr=_cfg.SMTP_FROM_HELLO,
            context={
                "license_key": license_key,
                "company_name": company_name,
                "plan": plan,
                "seats": seats,
                "landing_url": landing_url,
            },
        )

    async def send_welcome(
        self, *, to: str, company_name: str, landing_url: str,
        locale: str = DEFAULT_LOCALE,
    ) -> bool:
        from ..config import settings as _cfg
        return await self.send(
            to=to,
            template="welcome",
            locale=locale,
            from_addr=_cfg.SMTP_FROM_HELLO,
            context={"company_name": company_name, "landing_url": landing_url},
        )

    # ── Trial lifecycle ─────────────────────────────────────────────────────

    async def send_trial_expiring(
        self, *, to: str, full_name: str, days_left: int, expires_at_human: str,
        license_key: str, landing_url: str,
        locale: str = DEFAULT_LOCALE,
    ) -> bool:
        """T-7 / T-3 / T-1 / T+0 reminder. Single template parameterised by
        ``days_left`` (0 means already expired). Subject derived inside the
        template based on the same flag — one source of truth."""
        from ..config import settings as _cfg
        return await self.send(
            to=to, template="trial_expiring", locale=locale,
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
        locale: str = DEFAULT_LOCALE,
    ) -> bool:
        """Sent after admin runs POST /admin/tenants/:id/extend so the
        customer knows they got more time / a comp year."""
        from ..config import settings as _cfg
        return await self.send(
            to=to,
            template="license_extended",
            locale=locale,
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
    # These are operations telemetry read only by Dias. Locale-fixed at EN —
    # restyling/translating is pure overhead since they're not brand surface.

    async def send_admin_signup_notification(
        self, *, to: str, signup_email: str, full_name: str,
        country: str, intended_use: str, signup_source: str | None,
        ip: str, tenant_id: str,
    ) -> bool:
        from ..config import settings as _cfg
        return await self.send(
            to=to,
            subject=f"[lead] {full_name} from {country} — dias.now trial signup",
            template="admin_signup_notification",
            locale=DEFAULT_LOCALE,
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
            "password_changed":          "[security] Your dias.now admin password was changed",
            "backup_codes_regenerated":  "[security] Your dias.now admin backup codes were regenerated",
            "account_locked":            "[security] dias.now admin account locked due to failed logins",
            "totp_enrolled":             "[security] A new authenticator was enrolled on your dias.now admin",
        }
        return await self.send(
            to=to,
            subject=subject_map.get(kind, "[security] dias.now admin event"),
            template="admin_security_alert",
            locale=DEFAULT_LOCALE,
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
