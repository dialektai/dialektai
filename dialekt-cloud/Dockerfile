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

# Build context is the monorepo root (set in docker-compose.yml).
# Paths below reference dialekt-cloud/* explicitly to address that.
# Order matters for editable installs: the src/ package must exist
# at pip-install time or hatchling refuses to build the wheel.
COPY dialekt-cloud/pyproject.toml ./
COPY dialekt-cloud/src/ ./src/
RUN pip install --no-cache-dir -e ".[test]"

COPY dialekt-cloud/tests/ ./tests/

# Bundle the IBA agent manifests so library_seed._load_iba() can
# ship them as installable templates. ``parents[4]`` in the seeder
# resolves to ``/`` inside the container, so we drop the directory
# at /agents/iba/ to match. Local dev keeps reading them from the
# monorepo's ``agents/iba/`` via the same parents[4] math.
COPY agents/iba/ /agents/iba/

ENV INVOICES_DIR=/app/invoices
RUN mkdir -p /app/invoices

EXPOSE 8080

CMD ["uvicorn", "dialekt_cloud.main:app", "--host", "0.0.0.0", "--port", "8080"]
