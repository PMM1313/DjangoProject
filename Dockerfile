# =========================================================
# STAGE 1: Builder (Compiles wheels & dependencies)
# =========================================================
FROM python:3.8-slim AS builder

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

# Install Python packages to a isolated user location
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --user --no-cache-dir -r requirements.txt


# =========================================================
# STAGE 2: Final Runtime Image
# =========================================================
FROM python:3.8-slim AS runner

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV DEBIAN_FRONTEND=noninteractive
ENV PATH=/root/.local/bin:$PATH

WORKDIR /app

# Install runtime PostgreSQL client library and core system utilities
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy pre-built Python site-packages from the builder stage
COPY --from=builder /root/.local /root/.local

# Install Playwright browser binaries and OS dependencies
RUN playwright install --with-deps chromium \
    && rm -rf /var/lib/apt/lists/*

# Copy application source code
COPY . /app/

# Ensure entrypoint script is executable
RUN chmod +x /app/entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["/app/entrypoint.sh"]