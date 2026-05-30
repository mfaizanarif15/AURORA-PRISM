# AURORA PRISM

AURORA PRISM is a FastAPI + React + PostgreSQL MVP for podcast clip discovery. It accepts video, audio, transcript, guest/context data, and brand references; recommends short-form clips plus 3-6 minute highlights; supports approval; renders draft clips; and exports editor/social handoff packs.

For complete setup and startup instructions, see [SETUP.md](SETUP.md).
For backend endpoint contracts, see [API_REFERENCE.md](API_REFERENCE.md).
For PostgreSQL table details, see [DATABASE_TABLES.md](DATABASE_TABLES.md).

## Run With Docker

```bash
docker compose up --build
```

Frontend: `http://localhost:6173`  
Backend health: `http://localhost:8100/api/health`  
Backend API docs: `http://localhost:8100/docs`  
Langfuse status: `http://localhost:8100/api/observability/langfuse`  
Local Langfuse dashboard: `http://localhost:3005`

Backend logs are written to Docker output and to `storage/logs/backend.log` by default:

```bash
docker compose logs -f backend
```

To start local Langfuse too:

```bash
docker compose --profile langfuse up --build
```

Seed the provided Dr. Seth demo after the backend is running:

```bash
docker compose exec backend python scripts/seed_demo.py
```

## Backend

- FastAPI API under `/api`
- SQLAlchemy 2.0 async ORM
- Alembic migrations
- PostgreSQL storage with 12 application tables documented in [DATABASE_TABLES.md](DATABASE_TABLES.md)
- FFmpeg rendering inside the backend container
- `uv` is used for Python dependency management from `backend/pyproject.toml`
- Mock, hybrid, and LLM-only analysis modes for clip selection and platform metadata
- Azure OpenAI is the default AI provider, with standard OpenAI available as the second option
- Optional Langfuse observability for analysis, render, and export traces

Local backend with `uv`:

```bash
docker compose up -d postgres
cd backend
uv sync
source .venv/bin/activate
alembic upgrade head
uvicorn app.main:app --host 0.0.0.0 --port 8100 --reload
```

Or without activating:

```bash
docker compose up -d postgres
cd backend
uv run alembic upgrade head
uv run uvicorn app.main:app --host 0.0.0.0 --port 8100 --reload
uv run pytest
```

The backend loads the project `.env` from either the repo root or `backend/`. For local runs, use `DATABASE_URL=postgresql+asyncpg://aurora:aurora@localhost:55433/aurora_prism`. If the Docker backend is already running, port `8100` is busy; stop that service with `docker compose stop backend` or run local Uvicorn on another port, such as `8101`.

The app supports database-backed sign up and login. If the `users` table is empty, the configured local admin credentials can bootstrap the first user; change `AUTH_PASSWORD` and `AUTH_SESSION_SECRET` in `.env` for any shared environment. Episode history is scoped per user, so each signed-in user only sees and operates on episodes they created. The account settings dialog lets users update display name, username, and password. The workspace sidebar can be collapsed to a compact new-episode rail, and episode titles can be edited manually or generated from episode context; untitled episodes are also auto-titled after analysis.

## AI Provider Settings

Set `AI_PROVIDER=azure_openai` or `AI_PROVIDER=openai`. Azure OpenAI is the default.

For Azure OpenAI, use:

```bash
AZURE_OPENAI_ENDPOINT=
AZURE_OPENAI_API_KEY=
AZURE_OPENAI_API_VERSION=2025-03-01-preview
AZURE_OPENAI_CHAT_DEPLOYMENT=
```

The backend also supports the existing aliases `AZURE_API_BASE`, `AZURE_API_KEY`, `AZURE_API_VERSION`, and `AZURE_DEPLOYMENT`.

For standard OpenAI, use:

```bash
OPENAI_API_KEY=
OPENAI_MODEL=gpt-4.1-mini
```

Analysis modes:

- `mock`: local heuristic clip selection, no LLM call
- `hybrid`: LLM ranks/refines shortlisted candidates, then falls back to heuristics if the provider is unavailable
- `openai`: provider-backed LLM analysis is required

Langfuse traces for `hybrid` and `openai` analysis include an enterprise generation record named `llm_clip_analysis`. When `LANGFUSE_CAPTURE_LLM_IO=true`, the trace input contains the exact system/user chat messages and prompt payload, and the output contains the raw assistant JSON, parsed JSON, normalized clips, token usage, retry metadata, model, provider, and prompt version. Set `LANGFUSE_CAPTURE_LLM_IO=false` in sensitive environments to store hashes, lengths, and summaries instead of raw transcript/prompt text.

## Frontend

```bash
cd frontend
npm install
npm run dev
VITE_PROXY_TARGET=http://localhost:8101 npm run dev
```

The UI includes login/logout, episode intake, context setup, media/transcript uploads, clip instructions, PRISM Board filters, clip detail, approval actions, render controls, and export generation.

## Clip Modes

- Shorts: default 30-90 seconds for TikTok, YouTube Shorts, Instagram/Reels, and LinkedIn short posts.
- Highlights: default 3-6 minutes for deeper expert insight or story-based excerpts.
- Optional instructions can override target duration, clip count, platforms, and topic/style direction.

## Demo Assets

The Docker compose file mounts `Podcast Automation Assets/` into the backend container as `/app/demo-assets`. The seed script uses the Dr. Seth transcript, video, audio, questionnaire, and content brief from that folder.
