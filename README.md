# Hop

Hop is a discovery app: one click on the Hop button shows a page the user is likely to enjoy but would never have found.

**Status:** in progress. Phases 1 (skeleton) and 2 (Hop MVP) are complete: users can sign up, pick interests, hop, and like pages. Phase 3 (ingestion pipeline) is complete: a background worker fetches, cleans, and deduplicates new pages, uses an LLM, embeddings, and a safety screen to approve, reject, or flag them for review, re-checks approved pages every 30 days to retire broken ones, and finds new pages by itself from RSS/Atom feeds and from the links inside approved pages. Phase 4 (recommendations) is complete: a recommender (taste embeddings and Thompson sampling) runs as an A/B test against random picks, served from per-user Redis queues that cut p95 hop latency from 208 ms to 37 ms. Phase 5 (AI curator) is complete: a LangGraph agent with read-only tools reviews the pages the automatic checks couldn't decide, behind code guardrails it can't override, and admins decide the rest on a review screen where they can also remove or purge any page. A labeled evaluation set of 33 pages measures the agent: the first run scored 91% accuracy but let one manipulative page through, which led to a code-level injection check; the second run scored 91% with zero harmful approvals. Injection tests run in CI on every push. Phase 6 (hardening) is in progress: sign-up, login, and email confirmation are rate limited, and the crawler connects only to the address it checked, which closes DNS rebinding.

[![CI](https://github.com/tjonadibernice/hop/actions/workflows/ci.yml/badge.svg)](https://github.com/tjonadibernice/hop/actions/workflows/ci.yml)

## Tech stack

| Layer | Technology |
| --- | --- |
| Frontend | React, TypeScript, Vite, React Router |
| Backend | Python, FastAPI, SQLAlchemy, Alembic |
| Database | PostgreSQL with pgvector |
| Cache, sessions, and queues | Redis |
| Background jobs | taskiq with Redis Streams |
| Article extraction | trafilatura |
| Enrichment | Gemini, OpenAI, or Ollama (with failover); Voyage AI embeddings; Google Safe Browsing |
| Curator agent | LangGraph, with LangChain's OpenAI-compatible chat client |
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

7. (Optional) Try the ingestion pipeline. Start the worker in a new terminal, then queue the sample URLs in `backend/scripts/sources.txt`:

```bash
    make worker
    make ingest
```

The worker's log shows what happened to each URL. Each new page is then enriched and marked `approved` (it appears in Hop), `rejected`, or `needs_review`. Enrichment needs at least one LLM key in `.env`; see [Enrichment API keys](backend/README.md#enrichment-api-keys).

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
| `make worker` | Start the background worker for the ingestion pipeline |
| `make scheduler` | Start the scheduler that runs the daily link check (run only one) |
| `make ingest` | Queue the URLs in `backend/scripts/sources.txt` (or `make ingest f=path/to/list.txt`) |
| `make enrich` | Queue pending pages that haven't been enriched yet (after adding keys, or after an outage) |
| `make check-links` | Run the link check now instead of waiting for the daily schedule |
| `make poll-feeds` | Check the feeds in `backend/app/ingestion/feeds.txt` now |
| `make embed` | Add embeddings to approved pages that don't have one (needs `VOYAGE_API_KEY`) |
| `make ab-report` | Compare liked rates: recommender vs. random picks |
| `make curate` | Queue every `needs_review` page the curator agent hasn't reviewed yet (the worker must be running) |
| `make eval-curator` | Score the curator on the labeled evaluation set with the real LLM (`make eval-curator args="--tag injection"` for some cases) |
| `make loadtest` | Load test `POST /hop` in its own database and report latency (`make loadtest args="--no-queue"` to compare) |
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

- [Backend README](backend/README.md): API setup, endpoints, sign-up and login, hopping, iframe checks, the ingestion pipeline, the curator agent, its evaluation and prompt-injection defenses, migrations, tests
- [Frontend README](frontend/README.md): pages, light and night themes, the Hop screen, login state, API proxy, scripts