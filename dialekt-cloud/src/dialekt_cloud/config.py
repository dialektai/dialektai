from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    DATABASE_URL: str = "postgresql://dialekt_cloud:dialekt_cloud@localhost:5432/dialekt_cloud"
    # Break-glass admin key. Per admin_2fa_DESIGN: header-only auth (X-Admin-Key),
    # NEVER renders to HTML, NEVER mints a session cookie. Daily admin
    # auth uses email + argon2 password + TOTP via the `admins` table.
    DIALEKT_ADMIN_KEY: str = "aaaa" * 16  # 64 chars — must be overridden in production
    JWT_SECRET: str = "dev_secret"
    # 32 bytes base64 — encrypts admins.totp_secret_encrypted at rest.
    # Must be set in production; dev placeholder so tests run.
    DIALEKT_ADMIN_TOTP_KEY: str = "dGVzdC10b3RwLWtleS0zMmJ5dGVzLWxvbmcuLi4uLi4="
    # Allowed domain suffix for admin email addresses (case-insensitive).
    # Production policy: only @dias.now staff can hold admin accounts.
    # Tests / dev override via env var (set to empty string = no restriction).
    DIALEKT_ADMIN_EMAIL_DOMAIN: str = "@dias.now"

    # SMTP — production target is Zoho (smtp.zoho.com:465 implicit TLS).
    SMTP_HOST: str = "smtp.zoho.com"
    SMTP_PORT: int = 465
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM: str = "dias.now <hello@dias.now>"   # default sender (transactional)
    SMTP_TLS: bool = True

    # ── Per-purpose From-addresses (Zoho aliases on @dias.now) ──────────────
    # The email service routes by category so security alerts come from
    # security@, billing/invoices come from billing@, compliance from
    # privacy@. Keeps headers honest in inboxes and gives users somewhere
    # appropriate to reply.
    SMTP_FROM_HELLO:    str = "dias.now <hello@dias.now>"
    SMTP_FROM_SECURITY: str = "dias.now security <security@dias.now>"
    SMTP_FROM_PRIVACY:  str = "dias.now privacy <privacy@dias.now>"
    SMTP_FROM_BILLING:  str = "dias.now billing <billing@dias.now>"
    # Inbox that receives admin/internal notifications (new signups, lead
    # alerts, lockout broadcasts). Defaults to hello@ which fans out via
    # Zoho aliases; override to a personal mailbox for on-call.
    ADMIN_NOTIFY_TO: str = "hello@dias.now"

    # URLs
    APP_URL: str = "https://api.dias.now"
    ADMIN_URL: str = "https://admin.dias.now"
    LANDING_URL: str = "https://dialekt.dias.now"

    # Invoice
    INVOICE_SELLER_NAME: str = "ИП Founder"
    INVOICE_SELLER_BIN: str = ""
    INVOICE_SELLER_IBAN: str = ""
    INVOICE_SELLER_BANK: str = ""
    INVOICE_SELLER_BIK: str = ""
    INVOICE_SELLER_ADDRESS: str = ""
    INVOICE_SELLER_PHONE: str = ""
    INVOICE_SELLER_EMAIL: str = ""

    ENV: str = "development"
    LOG_LEVEL: str = "INFO"


settings = Settings()


# ── Production safety checks ──────────────────────────────────────────────────
#
# Refuse to boot a production process that's still using dev defaults for
# security-critical knobs. Better to crash on startup with a clear error
# than silently leak credentials or run with weak signing keys.
#
# Tests bypass this by leaving ENV="development". Production deploys MUST
# set ENV=production AND override every flagged value via .env or env vars.

_DEV_DEFAULTS = {
    "DIALEKT_ADMIN_KEY":      ("aaaa" * 16),
    "JWT_SECRET":             "dev_secret",
    "DIALEKT_ADMIN_TOTP_KEY": "dGVzdC10b3RwLWtleS0zMmJ5dGVzLWxvbmcuLi4uLi4=",
}


def _is_dev_default(name: str) -> bool:
    return getattr(settings, name) == _DEV_DEFAULTS.get(name)


def assert_production_ready() -> list[str]:
    """Returns a list of human-readable problems that block prod launch.
    Empty list = production-ready. Called from main.lifespan when ENV=production."""
    problems: list[str] = []

    if settings.ENV != "production":
        return problems  # only enforced in prod

    for name in _DEV_DEFAULTS:
        if _is_dev_default(name):
            problems.append(
                f"{name} is still the dev default — generate a fresh value and set in .env"
            )

    # SMTP must be wired or admins/users get no emails — half the v0.22
    # feature set silently no-ops without it.
    if not settings.SMTP_PASSWORD:
        problems.append(
            "SMTP_PASSWORD is empty — admins and users will receive NO emails. "
            "Generate a Zoho app password and set it in .env."
        )
    if not settings.SMTP_USER:
        problems.append("SMTP_USER is empty — set it to the Zoho mailbox doing the SMTP auth.")

    # Admin email domain policy must be set in prod.
    if not settings.DIALEKT_ADMIN_EMAIL_DOMAIN:
        problems.append(
            "DIALEKT_ADMIN_EMAIL_DOMAIN is empty in production — that's a no-restriction policy. "
            "Set it to '@dias.now' (or whatever the staff domain is)."
        )

    # AES-GCM key must decode to exactly 32 bytes.
    try:
        import base64
        raw = base64.b64decode(settings.DIALEKT_ADMIN_TOTP_KEY)
        if len(raw) != 32:
            problems.append(
                f"DIALEKT_ADMIN_TOTP_KEY decodes to {len(raw)} bytes — must be exactly 32 (base64 of os.urandom(32))."
            )
    except Exception as exc:
        problems.append(f"DIALEKT_ADMIN_TOTP_KEY is not valid base64: {exc}")

    # Invoice-seller fields must be set if any tenants might be invoiced.
    if not settings.INVOICE_SELLER_BIN or not settings.INVOICE_SELLER_IBAN:
        problems.append(
            "INVOICE_SELLER_BIN / INVOICE_SELLER_IBAN are empty — invoice generation will produce broken PDFs. "
            "Set the company's actual KZ-tax details before issuing the first invoice."
        )

    return problems
