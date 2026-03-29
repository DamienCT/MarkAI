# Stage 1: Install dependencies
FROM python:3.13-slim AS builder

WORKDIR /build

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
        unixodbc-dev \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir --upgrade pip hatchling

# Copy everything needed for the build
COPY pyproject.toml .
COPY app/ app/

RUN pip install --no-cache-dir .

# Stage 2: Runtime
FROM python:3.13-slim

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        libpq5 \
        unixodbc \
        curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY --from=builder /usr/local/lib/python3.13/site-packages /usr/local/lib/python3.13/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# I-H6: Run as non-root user
RUN adduser --system --uid 1001 appuser

COPY alembic.ini .
COPY alembic/ alembic/
COPY app/ app/

RUN chown -R appuser /app
USER appuser

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
