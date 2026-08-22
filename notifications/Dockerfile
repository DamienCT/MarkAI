# Stage 1: Install dependencies
FROM python:3.13-slim AS builder

WORKDIR /build

RUN pip install --no-cache-dir --upgrade pip hatchling

# P0-12: install the locked dependency set first (uv-generated universal
# lock, see requirements.lock), then the package itself without re-resolving.
COPY pyproject.toml requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock

COPY app/ app/

RUN pip install --no-cache-dir --no-deps .

# Stage 2: Runtime
FROM python:3.13-slim

RUN apt-get update && \
    apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY --from=builder /usr/local/lib/python3.13/site-packages /usr/local/lib/python3.13/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# I-H6: Run as non-root user
RUN adduser --system --uid 1001 appuser

COPY app/ app/

RUN chown -R appuser /app
USER appuser

EXPOSE 8002

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8002"]
