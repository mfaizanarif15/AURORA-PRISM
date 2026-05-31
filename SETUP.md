# AURORA PRISM Setup Guide

This guide explains how to configure, start, seed, and validate the AURORA PRISM MVP.

## Prerequisites

- Docker and Docker Compose
- Node.js 24+ only if running the frontend outside Docker
- Python 3.12 only if running the backend outside Docker
- FFmpeg only if rendering media while running the backend outside Docker
- The provided `Podcast Automation Assets/` folder in the project root

The recommended setup is Docker. The backend Docker image installs Python dependencies from `backend/pyproject.toml` with `uv`. You can also run the backend locally with `uv` and `backend/.venv`.

## 1. Create Environment File

From the project root:

```bash
cp .env.example .env
```

Open `.env` and configure the AI provider.

The app uses database-backed sign up and login. These local admin values can bootstrap the first user if the `users` table is empty:

```bash
AUTH_USERNAME=admin
AUTH_PASSWORD=aurora-admin
AUTH_SESSION_SECRET=change-this-session-secret
```

Replace the password and session secret for any shared environment. New users can also be created from the sign-up option on the login screen.

Episode history is scoped per user. After sign in, a user only sees and operates on episodes they own; direct links to another user's episodes, clips, renders, or exports return `404`. Use the settings button in the user profile area to update display name, username, or password. New episodes can start as untitled workspaces, then be renamed from Episode details or titled automatically from available context after analysis.

Azure OpenAI is the default:

```bash
AI_PROVIDER=azure_openai
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
AZURE_OPENAI_API_KEY=your-azure-key
AZURE_OPENAI_API_VERSION=2025-03-01-preview
AZURE_OPENAI_CHAT_DEPLOYMENT=your-chat-deployment-name
AZURE_OPENAI_TRANSCRIPTION_DEPLOYMENT=your-whisper-or-transcription-deployment-name
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
OPENAI_TRANSCRIPTION_MODEL=whisper-1
```

Audio uploads use standard OpenAI Whisper transcription when `OPENAI_API_KEY` is set. If no OpenAI key or Azure transcription deployment is configured, the audio asset is saved and transcription is skipped without replacing any existing transcript.

Analysis runs can use three modes from the UI/API:

- `mock`: local heuristic clip selection, no LLM call
- `hybrid`: LLM ranks/refines shortlisted candidates, then falls back to heuristics if the provider is unavailable
- `openai`: provider-backed LLM analysis is required

Local Langfuse observability is configured by default for Docker:

```bash
LANGFUSE_ENABLED=true
LANGFUSE_PUBLIC_KEY=pk-lf-aurora-prism-local
LANGFUSE_SECRET_KEY=sk-lf-aurora-prism-local
LANGFUSE_BASE_URL=http://localhost:3005
LANGFUSE_DOCKER_BASE_URL=http://host.docker.internal:3005
LANGFUSE_ENVIRONMENT=local
LANGFUSE_RELEASE=aurora-prism-mvp
LANGFUSE_CAPTURE_LLM_IO=true
LANGFUSE_MAX_LLM_IO_CHARS=250000
LANGFUSE_HOST_PORT=3005
LANGFUSE_INIT_ORG_NAME=AURORA PRISM Local
LANGFUSE_INIT_PROJECT_NAME=AURORA PRISM Local
```

Important: `LANGFUSE_BASE_URL=http://localhost:3005` is for local Uvicorn. Docker Compose uses `LANGFUSE_DOCKER_BASE_URL=http://host.docker.internal:3005` so the backend container can reach the Langfuse dashboard published on your host. The browser dashboard URL is `http://localhost:3005`.

For LLM analysis, open the `llm_clip_analysis` generation in Langfuse. With `LANGFUSE_CAPTURE_LLM_IO=true`, Input shows the exact system and user messages plus the structured prompt payload. Output shows the raw assistant JSON, parsed JSON, normalized clips, token usage, model parameters, retry count, provider, model, and prompt version. Set `LANGFUSE_CAPTURE_LLM_IO=false` if you need privacy-safe traces that keep only hashes, lengths, IDs, and summaries. `LANGFUSE_MAX_LLM_IO_CHARS` limits very large text fields before they are sent to Langfuse.

The `LANGFUSE_INIT_*` values are used only when the local Langfuse database is empty. To rename an existing local project, create or rename it inside the Langfuse UI, or reset the Langfuse volumes before starting the profile again.

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
- Local Langfuse dashboard: `http://localhost:3005`
- Postgres from host machine: `localhost:55433`

Database table details are documented in [DATABASE_TABLES.md](DATABASE_TABLES.md).

The backend container automatically runs:

```bash
alembic upgrade head
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

If you run the backend locally with Uvicorn while the Docker backend is still running, host port `8100` will already be occupied. Stop the Docker backend with `docker compose stop backend` or run local Uvicorn on another port, for example `--port 8101`.

## 2.1 View The Database In pgAdmin

Use these pgAdmin connection values for the main AURORA PRISM app database:

| Field | Value |
| --- | --- |
| Host name/address | `localhost` |
| Port | `55433` |
| Maintenance database | `aurora_prism` |
| Username | `aurora` |
| Password | `aurora` |

The app uses PostgreSQL and currently has 12 application tables. See [DATABASE_TABLES.md](DATABASE_TABLES.md) for the full table list, columns, relationships, and indexes.

## 3. Seed The Demo Episode

After Docker is running:

```bash
docker compose exec backend python scripts/seed_demo.py
```

This loads the Dr. Seth demo episode from:

```text
Podcast Automation Assets/
```

The seed script uses the transcript, video, audio, content PDF, and questionnaire PDF, then creates mock output recommendations.

## 4. Use The App

1. Open `http://localhost:6173`.
2. Sign in with the configured bootstrap credentials or create a user with the sign-up option.
3. Select or create an episode.
4. Upload video, audio, transcript, or guest documents.
5. Add context: Ideal Customer Profile, hot topic, business goals, and editor notes.
6. Choose output settings:
   - Shorts: 30-90 seconds
   - Highlights: 3-6 minutes
   - Optional custom duration, clip count, platforms, and instructions
7. Select AI provider: Azure OpenAI or OpenAI.
8. Click Analyze.
9. Review section outputs in the Outputs board.
10. Approve or reject outputs.
11. Render approved outputs.
12. Export the handoff ZIP.

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

Docker is still supported. If you want faster backend iteration outside Docker, use `uv` from the backend directory:

Install FFmpeg on the host before using the render button with local Uvicorn:

```bash
sudo apt update
sudo apt install ffmpeg
ffmpeg -version
```

```bash
docker compose up -d postgres
cd backend
uv sync
source .venv/bin/activate
alembic upgrade head
uvicorn app.main:app --host 0.0.0.0 --port 8101 --reload
```

You can also run without activating the virtualenv:

```bash
docker compose up -d postgres
cd backend
uv run alembic upgrade head
uv run uvicorn app.main:app --host 0.0.0.0 --port 8101 --reload
uv run pytest
```

The backend loads `.env` from the repo root or `backend/`, so commands work after `cd backend`. For local backend development, make sure `.env` has a local database URL:

```bash
DATABASE_URL=postgresql+asyncpg://aurora:aurora@localhost:55433/aurora_prism
STORAGE_ROOT=./storage
```

If Langfuse is enabled outside Docker, use a host URL such as `LANGFUSE_BASE_URL=http://localhost:3005`, or set `LANGFUSE_ENABLED=false` while developing locally.

You can run only Postgres with:

```bash
docker compose up -d postgres
```

Then use:

```text
Backend: http://localhost:8100
API docs: http://localhost:8100/docs
Health: http://localhost:8100/api/health
```

## 7. Local Frontend Development

```bash
cd frontend
npm install
npm run dev
VITE_PROXY_TARGET=http://localhost:8101 npm run dev
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

If an audio transcript upload is skipped, set `OPENAI_API_KEY` to enable OpenAI Whisper transcription or set `AZURE_OPENAI_TRANSCRIPTION_DEPLOYMENT` with the Azure endpoint and key.

If rendering fails, check backend logs. FFmpeg is installed inside the backend Docker image. For local Uvicorn, confirm `ffmpeg` is installed on the host:

```bash
command -v ffmpeg
docker compose logs -f backend
```

If Langfuse traces do not appear:

```bash
curl http://localhost:8100/api/observability/langfuse
docker compose logs -f backend
docker compose --profile langfuse logs -f langfuse-web
docker compose --profile langfuse logs -f langfuse-worker
```

Confirm `LANGFUSE_ENABLED=true`, both Langfuse keys are present, local Uvicorn uses `LANGFUSE_BASE_URL=http://localhost:3005`, and Docker backend uses `LANGFUSE_DOCKER_BASE_URL=http://host.docker.internal:3005`.

If the database schema is missing:

```bash
docker compose exec backend alembic upgrade head
```

If the demo episode does not appear:

```bash
docker compose exec backend python scripts/seed_demo.py
```
