"""Invoice PDF generation — Kazakhstan format."""
import os
from datetime import datetime, timezone
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

INVOICE_TEMPLATE_DIR = Path(__file__).parent.parent / "templates" / "invoice"
INVOICES_DIR = Path(os.environ.get("INVOICES_DIR", "/tmp/dialekt-invoices"))

_env = Environment(loader=FileSystemLoader(str(INVOICE_TEMPLATE_DIR)), autoescape=True)


def _next_invoice_number() -> str:
    year = datetime.now(timezone.utc).year
    # Simple sequential numbering; in production use DB sequence
    existing = list(INVOICES_DIR.glob(f"INV-{year}-*.pdf")) if INVOICES_DIR.exists() else []
    n = len(existing) + 1
    return f"INV-{year}-{n:04d}"


def generate_pdf(
    *,
    invoice_number: str,
    company_name: str,
    company_address: str | None,
    plan: str,
    seats: int,
    period_months: int,
    amount_kzt: float,
    seller: dict,
) -> Path:
    """Render invoice HTML → PDF. Returns path to generated PDF file."""
    try:
        import weasyprint
    except ImportError:
        raise RuntimeError("weasyprint not installed; install with: pip install weasyprint")

    INVOICES_DIR.mkdir(parents=True, exist_ok=True)
    template = _env.get_template("invoice_kz.html")
    now = datetime.now(timezone.utc)

    html_content = template.render(
        invoice_number=invoice_number,
        issued_date=now.strftime("%d.%m.%Y"),
        seller=seller,
        buyer_company=company_name,
        buyer_address=company_address or "",
        plan=plan,
        seats=seats,
        period_months=period_months,
        amount_kzt=amount_kzt,
        amount_kzt_fmt=f"{amount_kzt:,.0f}".replace(",", " "),
        has_nds=False,
    )

    pdf_path = INVOICES_DIR / f"{invoice_number}.pdf"
    weasyprint.HTML(string=html_content, base_url=str(INVOICE_TEMPLATE_DIR)).write_pdf(
        str(pdf_path)
    )
    return pdf_path


def seller_from_env() -> dict:
    return {
        "name": os.environ.get("INVOICE_SELLER_NAME", ""),
        "bin": os.environ.get("INVOICE_SELLER_BIN", ""),
        "iban": os.environ.get("INVOICE_SELLER_IBAN", ""),
        "bank": os.environ.get("INVOICE_SELLER_BANK", ""),
        "bik": os.environ.get("INVOICE_SELLER_BIK", ""),
        "address": os.environ.get("INVOICE_SELLER_ADDRESS", ""),
        "phone": os.environ.get("INVOICE_SELLER_PHONE", ""),
        "email": os.environ.get("INVOICE_SELLER_EMAIL", ""),
    }
