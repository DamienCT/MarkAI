# MARKAI

MARKAI is an AI-powered marketing automation platform that orchestrates content creation, social media publishing, competitor intelligence, and performance analytics for brand teams. It combines LangGraph agent workers, a FastAPI backend, and a Next.js frontend with integrated observability, all running as a 17-service Docker Compose stack. Social publishing runs natively in the backend — per-brand channel credentials are configured in the UI (see `docs/CHANNEL_CREDENTIALS.md`).

## Architecture

| Layer | Services |
|-------|----------|
| Edge | Traefik (reverse proxy) |
| Application | Next.js frontend, FastAPI backend (incl. native social publishing), LangGraph agents, Playwright browser worker, Notifications (Teams + SSE) |
| Data | PostgreSQL 16, Qdrant (vector DB), MinIO (object storage) |
| Infrastructure | NATS JetStream (message broker), Valkey (cache), LiteLLM (LLM gateway) |
| Observability | Prometheus, Grafana, Loki, OpenTelemetry Collector, Promtail |

## Prerequisites

- Docker Engine 24+ and Docker Compose v2
- At least 8 GB RAM available for containers
- API keys: OpenAI and/or Google Gemini
- Microsoft Entra ID app registration (for SSO)
- A configured `.env` file (copy `.env.example` and fill in secrets)

## Quick Start

```bash
# Clone and configure
cp .env.example .env
# Edit .env with your API keys and secrets

# Start all services (local dev with hot-reload)
docker compose up -d

# Frontend: http://localhost:3000
# Backend API: http://localhost:8000/docs
# Grafana dashboards: http://localhost:3001
```

## Development Setup

```bash
# Backend (FastAPI)
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000

# Frontend (Next.js)
cd frontend
npm install
npm run dev

# Agents
cd agents
pip install -r requirements.txt
python -m worker
```

## Running Tests

```bash
# Backend tests
cd backend && pytest

# Frontend tests
cd frontend && npm test
```

## Deployment

For VPS/production deployment, see `docs/build-files/MARKAI-Setup-Guide-v2.md`.

```bash
# Production compose (with VPS overlay)
docker compose -f docker-compose.yml -f docker-compose.vps.yml up -d
```
