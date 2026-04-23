FROM python:3.12-slim

# WeasyPrint dependencies (for PDF generation)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpango-1.0-0 libpangoft2-1.0-0 libpangocairo-1.0-0 \
    libcairo2 libgdk-pixbuf2.0-0 libffi-dev shared-mime-info \
    fonts-liberation curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml ./
RUN pip install --no-cache-dir -e ".[test]"

COPY src/ ./src/
COPY tests/ ./tests/

ENV INVOICES_DIR=/app/invoices
RUN mkdir -p /app/invoices

EXPOSE 8080

CMD ["uvicorn", "dialekt_cloud.main:app", "--host", "0.0.0.0", "--port", "8080"]
