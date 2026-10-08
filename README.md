# Hop

Hop is a discovery app: one click on the Hop button shows a page the user is likely to enjoy but would never have found.

**Status:** in progress. Phase 1 (project skeleton) is being built.

## Tech stack

| Layer | Technology |
| --- | --- |
| Frontend | React, TypeScript, Vite |
| Backend | Python, FastAPI |
| Database | PostgreSQL with pgvector |
| Cache and queues | Redis |
| Local environment | Docker Compose |

## Project structure

```
hop/
├── backend/            # FastAPI API
├── frontend/           # React app
├── docker-compose.yml  # Postgres and Redis for local development
├── init.sql            # Enables pgvector when the database is first created
└── .env.example        # Environment variables template
```

## Quick start

**Requirements:** Docker, Python 3.12+ with [uv](https://docs.astral.sh/uv/), and Node.js (current LTS).

1. Create your environment file and fill in real values:

```bash
    cp .env.example .env
```

2. Start Postgres and Redis:

```bash
    docker compose up -d
```

3. Start the backend (in a new terminal):

```bash
    cd backend
    uv sync
    uv run uvicorn app.main:app --reload
```

4. Start the frontend (in another terminal):

```bash
    cd frontend
    npm install
    npm run dev
```

5. Open http://localhost:5173. The page shows whether the API, Postgres, and Redis are healthy.

## Common commands

| Target | Description |
| --- | --- |
| `make up` | Start Postgres and Redis in the background |
| `make down` | Stop Postgres and Redis |
| `make api` | Start the backend with reload |
| `make web` | Start the frontend development server |
| `make lint` | Run Ruff and ESLint |
| `make test` | Run backend pytest tests |
| `make build` | Build the frontend production bundle |
| `make format` | Format backend and frontend code |
| `make check` | Run lint, tests, and the frontend build |

## More details

- [Backend README](backend/README.md): API setup, health checks, tests
- [Frontend README](frontend/README.md): frontend setup, API proxy, scripts
