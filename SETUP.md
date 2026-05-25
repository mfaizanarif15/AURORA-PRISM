# AURORA PRISM Setup Guide

This guide explains how to configure, start, seed, and validate the AURORA PRISM MVP.

## Prerequisites

- Docker and Docker Compose
- Node.js 24+ only if running the frontend outside Docker
- Python 3.12 only if running the backend outside Docker
- The provided `Podcast Automation Assets/` folder in the project root

The recommended setup is Docker. The backend Docker image installs Python dependencies with `uv` inside the container and does not require a local virtual environment.

## 1. Create Environment File

From the project root:

```bash
cp .env.example .env
```

Open `.env` and configure the AI provider.

Azure OpenAI is the default:

```bash
AI_PROVIDER=azure_openai
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
AZURE_OPENAI_API_KEY=your-azure-key
AZURE_OPENAI_API_VERSION=2025-03-01-preview
AZURE_OPENAI_CHAT_DEPLOYMENT=your-chat-deployment-name
AZURE_OPENAI_EMBEDDING_DEPLOYMENT=text-embedding-3-large
```

Existing Azure aliases are also supported:

```bash
AZURE_API_BASE=
AZURE_API_KEY=
AZURE_API_VERSION=
AZURE_DEPLOYMENT=
```

To use standard OpenAI instead:

```bash
AI_PROVIDER=openai
OPENAI_API_KEY=your-openai-key
OPENAI_MODEL=gpt-4.1-mini
```

For a reliable local demo without live AI calls, keep:

```bash
ANALYSIS_MODE=true
```

Set `ANALYSIS_MODE=false` when you want live provider-backed analysis behavior.

Local Langfuse observability is configured by default for Docker:

```bash
LANGFUSE_ENABLED=true
LANGFUSE_PUBLIC_KEY=pk-lf-aurora-prism-local
LANGFUSE_SECRET_KEY=sk-lf-aurora-prism-local
LANGFUSE_BASE_URL=http://langfuse-web:3000
LANGFUSE_ENVIRONMENT=local
LANGFUSE_RELEASE=aurora-prism-mvp
```

Important: `LANGFUSE_BASE_URL=http://langfuse-web:3000` is the internal Docker URL used by the backend container. The browser dashboard URL is `http://localhost:3200`.

Local Langfuse login:

```text
Email: admin@aurora.local
Password: aurora-langfuse-local
```

If you prefer Langfuse Cloud instead, use `https://cloud.langfuse.com` or `https://us.cloud.langfuse.com` as `LANGFUSE_BASE_URL` and replace the local keys with your cloud project keys.

## 2. Start The Full App With Docker

Run from the project root:

```bash
docker compose up --build
```

To also start the local Langfuse dashboard and storage stack:

```bash
docker compose --profile langfuse up --build
```

Services:

- Frontend: `http://localhost:6173`
- Backend health: `http://localhost:8100/api/health`
- Backend API docs: `http://localhost:8100/docs`
- Langfuse status: `http://localhost:8100/api/observability/langfuse`
- Local Langfuse dashboard: `http://localhost:3200`
- Postgres from host machine: `localhost:55433`

The backend container automatically runs:

```bash
alembic upgrade head
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## 3. Seed The Demo Episode

After Docker is running:

```bash
docker compose exec backend python scripts/seed_demo.py
```

This loads the Dr. Seth demo episode from:

```text
Podcast Automation Assets/
```

The seed script uses the transcript, video, audio, content PDF, and questionnaire PDF, then creates mock/hybrid clip recommendations.

## 4. Use The App

1. Open `http://localhost:6173`.
2. Select or create an episode.
3. Upload video, audio, transcript, guest documents, guest images, or brand references.
4. Add context: ICP, hot topic, TKXEL services, business goals, and editor notes.
5. Choose clip settings:
   - Shorts: 30-90 seconds
   - Highlights: 3-6 minutes
   - Optional custom duration, clip count, platforms, and instructions
6. Select AI provider: Azure OpenAI or OpenAI.
7. Click Analyze.
8. Review clips in the PRISM Board.
9. Approve, reject, or request revisions.
10. Render approved clips.
11. Export the handoff ZIP.

## 5. Common Docker Commands

Start:

```bash
docker compose up --build
```

Run in background:

```bash
docker compose up --build -d
```

View logs:

```bash
docker compose logs -f backend
docker compose logs -f frontend
```

Stop:

```bash
docker compose down
```

Reset database and containers:

```bash
docker compose down -v
docker compose up --build
```

Run migrations manually:

```bash
docker compose exec backend alembic upgrade head
```

Run backend tests in Docker:

```bash
docker compose exec backend pytest
```

## 6. Local Backend Development

Docker is preferred. If you still want to run the backend locally, install dependencies using your own Python environment:

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload
```

For local backend development, make sure `.env` has a local database URL:

```bash
DATABASE_URL=postgresql+asyncpg://aurora:aurora@localhost:55433/aurora_prism
STORAGE_ROOT=./storage
```

You can run only Postgres with:

```bash
docker compose up postgres
```

## 7. Local Frontend Development

```bash
cd frontend
npm install
npm run dev
```

When running the frontend locally outside Docker, the Vite dev server proxies `/api` to `http://localhost:8100`.
Inside Docker, Compose sets `VITE_PROXY_TARGET=http://backend:8000` so the frontend container can reach the backend container.

Build check:

```bash
npm run build
```

Frontend tests:

```bash
npm test
```

## 8. Storage And Exports

Uploaded files and generated exports are stored under:

```text
storage/uploads/
storage/exports/
```

These folders are ignored by git.

Export packs include approved media, transcript excerpts, score reasoning, titles, hooks, captions, CTAs, thumbnail concepts, CSV, Markdown, PDF/DOCX, and a ZIP handoff package.

## 9. Troubleshooting

If Docker cannot access the daemon:

```bash
docker ps
```

If ports are already in use, stop the conflicting service or edit `docker-compose.yml` ports:

```text
8100:8000
6173:5173
55433:5432
```

If the backend cannot read `.env`, confirm the file exists in the project root:

```bash
ls -la .env
```

If Azure OpenAI is selected but not configured, ensure one of these pairs exists:

```bash
AZURE_OPENAI_ENDPOINT=...
AZURE_OPENAI_API_KEY=...
AZURE_OPENAI_CHAT_DEPLOYMENT=...
```

or:

```bash
AZURE_API_BASE=...
AZURE_API_KEY=...
AZURE_DEPLOYMENT=...
```

If rendering fails, check backend logs. FFmpeg is installed inside the backend Docker image:

```bash
docker compose logs -f backend
```

If Langfuse traces do not appear:

```bash
curl http://localhost:8100/api/observability/langfuse
docker compose logs -f backend
docker compose --profile langfuse logs -f langfuse-web
docker compose --profile langfuse logs -f langfuse-worker
```

Confirm `LANGFUSE_ENABLED=true`, both Langfuse keys are present, and `LANGFUSE_BASE_URL=http://langfuse-web:3000` for local Docker usage.

If the database schema is missing:

```bash
docker compose exec backend alembic upgrade head
```

If the demo episode does not appear:

```bash
docker compose exec backend python scripts/seed_demo.py
```
