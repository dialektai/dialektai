FROM python:3.12-slim-bookworm

# WeasyPrint dependencies (for PDF generation).
# Pin to Debian Bookworm because Trixie renames libgdk-pixbuf2.0-0 →
# libgdk-pixbuf-2.0-0 and the python:3.12-slim tag tracks the current
# Debian stable, which is Trixie as of mid-2025.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpango-1.0-0 libpangoft2-1.0-0 libpangocairo-1.0-0 \
    libcairo2 libgdk-pixbuf2.0-0 libffi-dev shared-mime-info \
    fonts-liberation curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Order matters for editable installs: the src/ package must exist
# at pip-install time or hatchling refuses to build the wheel.
COPY pyproject.toml ./
COPY src/ ./src/
RUN pip install --no-cache-dir -e ".[test]"

COPY tests/ ./tests/

ENV INVOICES_DIR=/app/invoices
RUN mkdir -p /app/invoices

EXPOSE 8080

CMD ["uvicorn", "dialekt_cloud.main:app", "--host", "0.0.0.0", "--port", "8080"]
