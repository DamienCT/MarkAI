# Stage 1: Build dependencies
FROM python:3.13-slim AS builder

WORKDIR /build

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
        unixodbc-dev \
        curl \
        gpg \
    && curl -fsSL https://packages.microsoft.com/keys/microsoft.asc | gpg --dearmor -o /etc/apt/keyrings/microsoft.gpg \
    && echo "deb [arch=amd64 signed-by=/etc/apt/keyrings/microsoft.gpg] https://packages.microsoft.com/debian/12/prod bookworm main" > /etc/apt/sources.list.d/mssql-release.list \
    && apt-get update && ACCEPT_EULA=Y apt-get install -y msodbcsql17 \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml .
COPY shared/ shared/
COPY workflows/ workflows/
COPY worker.py .
RUN pip install --no-cache-dir --prefix=/install .

# Stage 2: Runtime (slim — no build-essential)
FROM python:3.13-slim

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        libpq5 \
        unixodbc \
        imagemagick \
        fonts-dejavu-core \
        procps \
        curl \
        gpg \
    && curl -fsSL https://packages.microsoft.com/keys/microsoft.asc | gpg --dearmor -o /etc/apt/keyrings/microsoft.gpg \
    && echo "deb [arch=amd64 signed-by=/etc/apt/keyrings/microsoft.gpg] https://packages.microsoft.com/debian/12/prod bookworm main" > /etc/apt/sources.list.d/mssql-release.list \
    && apt-get update && ACCEPT_EULA=Y apt-get install -y msodbcsql17 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY --from=builder /install /usr/local

# Install Playwright Chromium and its OS-level dependencies
RUN playwright install --with-deps chromium

# I-H6: Run as non-root user
RUN adduser --system --uid 1001 appuser
USER appuser

COPY shared/ shared/
COPY workflows/ workflows/
COPY worker.py .

CMD ["python", "-m", "worker"]
