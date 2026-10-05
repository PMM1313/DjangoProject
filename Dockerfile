# =========================================================
# STAGE 1: Builder (Compiles wheels & dependencies)
# =========================================================
FROM python:3.12.10 AS builder

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV DEBIAN_FRONTEND=noninteractive

WORKDIR /app

# Install compilation tools needed for C-extensions (like psycopg2)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/

# Install Python packages to an isolated user location
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --user --no-cache-dir -r requirements.txt


# =========================================================
# STAGE 2: Slim runtime (web, celery worker, celery beat)
# =========================================================
FROM python:3.12.10-slim AS runner

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV DEBIAN_FRONTEND=noninteractive
ENV PATH=/root/.local/bin:$PATH

WORKDIR /app

# Install PostgreSQL runtime client libraries
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

# Copy pre-built Python packages from builder stage
COPY --from=builder /root/.local /root/.local

# Copy application source code
COPY . /app/

# Ensure entrypoint script is executable
RUN chmod +x /app/entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["web"]