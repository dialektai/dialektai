from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    DATABASE_URL: str = "postgresql://dialekt_cloud:dialekt_cloud@localhost:5432/dialekt_cloud"
    DIALEKT_ADMIN_KEY: str = "aaaa" * 16  # 64 chars — must be overridden in production
    JWT_SECRET: str = "dev_secret"

    # SMTP
    SMTP_HOST: str = "localhost"
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM: str = "dialekt.ai <noreply@dialekt.ai>"
    SMTP_TLS: bool = True

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
