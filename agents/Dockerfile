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
        librsvg2-bin \
        ffmpeg \
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

# Bundle popular display fonts for ad/poster headlines (OFL/Apache licensed,
# pulled from the Google Fonts repo). One handwritten face (Dancing Script).
RUN mkdir -p /usr/share/fonts/truetype/markai && cd /usr/share/fonts/truetype/markai && \
    curl -fsSL -o Montserrat.ttf "https://github.com/google/fonts/raw/main/ofl/montserrat/Montserrat%5Bwght%5D.ttf" && \
    curl -fsSL -o Poppins.ttf "https://github.com/google/fonts/raw/main/ofl/poppins/Poppins-Bold.ttf" && \
    curl -fsSL -o Oswald.ttf "https://github.com/google/fonts/raw/main/ofl/oswald/Oswald%5Bwght%5D.ttf" && \
    curl -fsSL -o PlayfairDisplay.ttf "https://github.com/google/fonts/raw/main/ofl/playfairdisplay/PlayfairDisplay%5Bwght%5D.ttf" && \
    curl -fsSL -o DancingScript.ttf "https://github.com/google/fonts/raw/main/ofl/dancingscript/DancingScript%5Bwght%5D.ttf" && \
    fc-cache -f

# Install Playwright Chromium and its OS-level dependencies
RUN playwright install --with-deps chromium

# I-H6: Run as non-root user
RUN adduser --system --uid 1001 appuser
USER appuser

COPY shared/ shared/
COPY workflows/ workflows/
COPY worker.py .
# Reel music beds (VIDEO_MUSIC_DIR). Ships empty — see assets/music/README.md:
# licensing is the operator's call, so the pipeline plays only what is put
# here. Without this COPY the directory simply does not exist in the image and
# every reel reports "no bed available", which is the honest outcome but not
# an obvious one to diagnose. Bind-mount over /app/assets/music instead if you
# would rather add tracks without a rebuild.
COPY assets/ assets/

CMD ["python", "-m", "worker"]
