# ============================================================
# SuryaGrid AI — Dockerfile
# Multi-stage build: Python 3.12-slim
# Runs FastAPI + embedded MQTT subscriber
# ============================================================

# ---- Stage 1: build deps in a full image -------------------
FROM python:3.12-slim AS builder

WORKDIR /build

# Install system deps needed to compile psycopg2-binary
RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc \
        libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt


# ---- Stage 2: lean runtime image ---------------------------
FROM python:3.12-slim AS runtime

# Non-root user for security
RUN addgroup --system surya && adduser --system --ingroup surya surya

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Copy application source
COPY app/ .

# Expose FastAPI port
EXPOSE 8000

# Switch to non-root
USER surya

# Health-check: hit /health every 30 s
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
