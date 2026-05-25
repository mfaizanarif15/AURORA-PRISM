# AURORA PRISM

AURORA PRISM is a FastAPI + React + PostgreSQL MVP for podcast clip discovery. It accepts video, audio, transcript, guest/context data, and brand references; recommends short-form clips plus 3-6 minute highlights; supports approval; renders draft clips; and exports editor/social handoff packs.

For complete setup and startup instructions, see [SETUP.md](SETUP.md).
For backend endpoint contracts, see [API_REFERENCE.md](API_REFERENCE.md).

## Run With Docker

```bash
docker compose up --build
```

Frontend: `http://localhost:6173`  
Backend health: `http://localhost:8100/api/health`  
Backend API docs: `http://localhost:8100/docs`  
Langfuse status: `http://localhost:8100/api/observability/langfuse`  
Local Langfuse dashboard: `http://localhost:3200`

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
- PostgreSQL storage
- FFmpeg rendering inside the backend container
- `uv` is used inside Docker for Python dependency installation; no local virtualenv is required
- Mock/hybrid analysis mode for reliable demos
- Azure OpenAI is the default AI provider, with standard OpenAI available as the second option
- Optional Langfuse observability for analysis, render, and export traces

Useful commands:

```bash
cd backend
alembic upgrade head
uvicorn app.main:app --reload
pytest
```

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

## Frontend

```bash
cd frontend
npm install
npm run dev
```

The UI includes episode intake, context setup, media/transcript uploads, clip instructions, PRISM Board filters, clip detail, approval actions, render controls, and export generation.

## Clip Modes

- Shorts: default 30-90 seconds for TikTok, YouTube Shorts, Instagram/Reels, and LinkedIn short posts.
- Highlights: default 3-6 minutes for deeper expert insight or story-based excerpts.
- Optional instructions can override target duration, clip count, platforms, and topic/style direction.

## Demo Assets

The Docker compose file mounts `Podcast Automation Assets/` into the backend container as `/app/demo-assets`. The seed script uses the Dr. Seth transcript, video, audio, questionnaire, and content brief from that folder.
