FROM python:3.13-slim

WORKDIR /app

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
        unixodbc-dev \
        imagemagick \
        fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml .
RUN pip install --no-cache-dir . && \
    playwright install --with-deps chromium

COPY shared/ shared/
COPY workflows/ workflows/
COPY worker.py .

CMD ["python", "-m", "worker"]
