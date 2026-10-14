# Hop

Hop is a discovery app: one click on the Hop button shows a page the user is likely to enjoy but would never have found.

**Status:** in progress. Phase 1 (project skeleton) is complete; Phase 2 (Hop MVP) is nearly complete: users can sign up, pick interests, hop, and like pages.

[![CI](https://github.com/tjonadibernice/hop/actions/workflows/ci.yml/badge.svg)](https://github.com/tjonadibernice/hop/actions/workflows/ci.yml)

## Tech stack

| Layer | Technology |
| --- | --- |
| Frontend | React, TypeScript, Vite, React Router |
| Backend | Python, FastAPI, SQLAlchemy, Alembic |
| Database | PostgreSQL with pgvector |
| Cache, sessions, and queues | Redis |
| Local email | Mailpit (catches all outgoing email) |
| Local environment | Docker Compose |
| CI | GitHub Actions |

## Project structure

```
hop/
├── backend/            # FastAPI API
├── frontend/           # React app
├── docker-compose.yml  # Postgres, Redis, and Mailpit for local development
├── init.sql            # Enables pgvector when the database is first created
├── Makefile            # Common commands
└── .env.example        # Environment variables template
```

## Quick start

**Requirements:** Docker, Python 3.12+ with [uv](https://docs.astral.sh/uv/), Node.js (current LTS), and `make`.

1. Create your environment file and fill in real values:

```bash
    cp .env.example .env
```

2. Install dependencies, start the services, set up the database, load the starter pages, and check which pages can be shown inside Hop:

```bash
    make install
    make up
    make migrate
    make seed
    make check-embeds
```

3. Create the test database (needed once, for `make test`):

```bash
    make test-db
```

4. Start the backend (in a new terminal):

```bash
    make api
```

5. Start the frontend (in another terminal):

```bash
    make web
```

6. Open http://localhost:5173 and sign up. The confirmation email arrives in Mailpit at http://localhost:8025; open the link, confirm, log in, pick your interests, and press **Hop**.

Emails never leave your machine: Mailpit catches all of them.

## Common commands

| Command | Description |
| --- | --- |
| `make install` | Install backend and frontend dependencies |
| `make up` | Start Postgres, Redis, and Mailpit in the background |
| `make down` | Stop the services |
| `make migrate` | Apply database migrations |
| `make migration m="message"` | Generate a new migration from model changes |
| `make seed` | Load the starter pages (safe to run again) |
| `make check-embeds` | Check which pages allow being shown in an iframe (only unchecked pages) |
| `make test-db` | Create the test database (once) |
| `make api` | Start the backend with reload |
| `make web` | Start the frontend development server |
| `make format` | Fix lint issues and format backend and frontend code |
| `make lint` | Run Ruff and ESLint |
| `make format-check` | Check formatting without changing files |
| `make test` | Run backend tests (needs Postgres running) |
| `make build` | Build the frontend production bundle |
| `make check` | Run lint, format check, tests, and the frontend build |

Before committing, run `make format` and `make check`.

## Contributing

Run `make check` before pushing. CI runs the same checks on every push to `main`.

## More details

- [Backend README](backend/README.md): API setup, endpoints, sign-up and login, hopping, iframe checks, migrations, tests
- [Frontend README](frontend/README.md): pages, the Hop screen, login state, API proxy, scripts