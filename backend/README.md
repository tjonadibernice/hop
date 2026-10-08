# Hop Backend

FastAPI service for Hop. It serves the API, connects to Postgres (with pgvector) and Redis, and exposes health checks.

## Requirements

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)
- Docker (for Postgres and Redis)

## Setup

From the project root:

```bash
cp .env.example .env      # then fill in real values
docker compose up -d      # start Postgres and Redis
```

From `backend/`:

```bash
uv sync                   # install dependencies
```

## Run the API

```bash
uv run uvicorn app.main:app --reload
```

- API: http://localhost:8000
- Interactive docs: http://localhost:8000/docs

## Health checks

| Endpoint | Checks | Returns |
| --- | --- | --- |
| `GET /health/live` | The process is running | Always `200` |
| `GET /health/ready` | Postgres and Redis respond within 2 seconds | `200` if both are OK, `503` if either fails |

## Tests and linting

```bash
uv run pytest
uv run ruff check .
uv run ruff format .
```

## Project structure

```
app/
├── main.py          # App setup, lifespan, routers
├── config.py        # Settings loaded from the root .env
├── db.py            # Postgres engine
├── cache.py         # Redis client
└── routers/
    └── health.py    # Health check endpoints
tests/
└── test_health.py
```