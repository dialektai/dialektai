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

    async def send(self, *, to: str, subject: str, template: str, context: dict) -> bool:
        try:
            html = self._env.get_template(f"{template}.html").render(**context)
            try:
                text = self._env.get_template(f"{template}.txt").render(**context)
            except Exception:
                text = subject  # fallback plain text

            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = self.from_addr
            msg["To"] = to
            msg.attach(MIMEText(text, "plain", "utf-8"))
            msg.attach(MIMEText(html, "html", "utf-8"))

            smtp_kwargs = dict(
                hostname=self.host,
                port=self.port,
            )
            if self.user:
                smtp_kwargs["username"] = self.user
                smtp_kwargs["password"] = self.password
            if self.use_tls:
                smtp_kwargs["use_tls"] = True

            await aiosmtplib.send(msg, **smtp_kwargs)
            logger.info("Email sent to %s (template=%s)", to, template)
            return True
        except Exception as exc:
            logger.error("Failed to send email to %s: %s", to, exc)
            return False

    async def send_invite(self, *, to: str, invite_token: str, company_name: str, landing_url: str) -> bool:
        return await self.send(
            to=to,
            subject=f"Приглашение в dialekt.ai — {company_name}",
            template="invite",
            context={
                "invite_token": invite_token,
                "company_name": company_name,
                "landing_url": landing_url,
                "invite_url": f"{landing_url}/invite/{invite_token}",
            },
        )

    async def send_license_activated(self, *, to: str, license_key: str, company_name: str, plan: str, seats: int, landing_url: str) -> bool:
        return await self.send(
            to=to,
            subject="Ваша лицензия dialekt.ai активирована",
            template="license_activated",
            context={
                "license_key": license_key,
                "company_name": company_name,
                "plan": plan,
                "seats": seats,
                "landing_url": landing_url,
            },
        )

    async def send_welcome(self, *, to: str, company_name: str, landing_url: str) -> bool:
        return await self.send(
            to=to,
            subject=f"Добро пожаловать в dialekt.ai",
            template="welcome",
            context={"company_name": company_name, "landing_url": landing_url},
        )
