# Stage 1: Install dependencies
FROM python:3.13-slim AS builder

WORKDIR /build

RUN pip install --no-cache-dir --upgrade pip

COPY pyproject.toml .
RUN pip install --no-cache-dir --prefix=/install .

# Stage 2: Runtime
FROM python:3.13-slim

WORKDIR /app

COPY --from=builder /install /usr/local

# Install Playwright Chromium and its OS-level dependencies
RUN playwright install chromium --with-deps

# I-H6: Run as non-root user
# Playwright browser cache is installed as root above; grant read access to appuser
RUN adduser --system --uid 1001 appuser

COPY app/ app/

RUN chown -R appuser /app
USER appuser

EXPOSE 8001

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]
