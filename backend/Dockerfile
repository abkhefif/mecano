# FINDING-H01: Multi-stage build — build tools are only present in the builder
# stage and are NOT copied into the final runtime image.
FROM python:3.12-slim AS builder

WORKDIR /app

# System build dependencies needed only at pip-install time
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# ── Runtime image ─────────────────────────────────────────────────────────────
FROM python:3.12-slim

WORKDIR /app

# Runtime-only system dependencies for WeasyPrint
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libgdk-pixbuf-2.0-0 \
    libffi8 \
    shared-mime-info \
    && rm -rf /var/lib/apt/lists/*

# Copy only the installed packages from the builder stage (no pip, no gcc)
COPY --from=builder /root/.local /root/.local

# Copy application source (only what is needed at runtime)
COPY app/ ./app/
COPY alembic/ ./alembic/
COPY alembic.ini .

RUN useradd -m appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=45s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

CMD ["sh", "-c", "python -m alembic upgrade head && gunicorn app.main:app --workers ${WEB_CONCURRENCY:-1} --worker-class uvicorn.workers.UvicornWorker --bind 0.0.0.0:8000 --timeout 120 --graceful-timeout 30 --max-requests 1000 --max-requests-jitter 100"]
