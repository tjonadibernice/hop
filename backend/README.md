# Hop Backend

FastAPI service for Hop. It serves the API, connects to Postgres (with pgvector) and Redis, handles sign-up with email verification and login with server-side sessions, stores users' interests, serves pages through the Hop endpoint, and records likes and dislikes. A background worker runs the ingestion pipeline, which fetches, cleans, and deduplicates new pages, then enriches them with an LLM and embeddings and decides which ones Hop shows. A daily scheduled job re-checks approved pages and retires the ones that broke.

## Requirements

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)
- Docker (for Postgres, Redis, and Mailpit)

## Setup

From the project root:

```bash
cp .env.example .env      # then fill in real values
make up                   # start Postgres, Redis, and Mailpit
make migrate              # apply database migrations
make seed                 # load the starter pages
make check-embeds         # check which pages can be shown in an iframe
make worker               # (optional) start the ingestion worker
make ingest               # (optional) queue the URLs in scripts/sources.txt
make enrich               # (optional) queue pending pages for enrichment
make scheduler            # (optional) run the daily link check
make test-db              # create the test database (once)
```

From `backend/`:

```bash
uv sync                   # install dependencies
```

### Settings

Settings are read from the root `.env`. Environment variables take priority.

| Variable | Required | Default | Purpose |
| --- | --- | --- | --- |
| `DATABASE_URL` | Yes | | Postgres connection for the app |
| `REDIS_URL` | Yes | | Redis connection (sessions and verification tokens) |
| `TEST_DATABASE_URL` | For tests | | Separate Postgres database used by the tests |
| `SMTP_HOST` | No | `localhost` | Email server (Mailpit locally) |
| `SMTP_PORT` | No | `1025` | Email server port |
| `MAIL_FROM` | No | `Hop <no-reply@hop.local>` | Sender of outgoing emails |
| `APP_BASE_URL` | No | `http://localhost:5173` | Frontend address, used for links in emails |
| `SESSION_COOKIE_NAME` | No | `hop_session` | Name of the session cookie |
| `SESSION_TTL_SECONDS` | No | `604800` (7 days) | How long a login lasts |
| `COOKIE_SECURE` | No | `false` | Send the session cookie over HTTPS only; set to `true` in production |
| `CRAWLER_USER_AGENT` | No | `HopBot/0.1 (+https://github.com/tjonadibernice/hop)` | How the crawler identifies itself to websites |
| `CRAWL_DELAY_SECONDS` | No | `1.0` | Minimum time between two requests to the same website |
| `CRAWL_ALLOW_PRIVATE_HOSTS` | No | `false` | Lets the crawler fetch localhost and private addresses. Only for local testing |
| `GEMINI_API_KEY` | For enrichment | | First LLM provider (model `GEMINI_MODEL`, default `gemini-3.1-flash-lite`) |
| `OPENAI_API_KEY` | No | | Second LLM provider (model `OPENAI_MODEL`, default `gpt-5.6-luna`) |
| `OLLAMA_BASE_URL` | No | | Third LLM provider, a local model, e.g. `http://localhost:11434/v1` (model `OLLAMA_MODEL`, default `llama3.2`) |
| `VOYAGE_API_KEY` | No | | Embeddings (model `VOYAGE_MODEL`, default `voyage-4-lite`); without it, pages have no embedding |
| `SAFE_BROWSING_API_KEY` | No | | Google Safe Browsing; without it, pages can't be auto-approved |

At least one of `GEMINI_API_KEY`, `OPENAI_API_KEY`, or `OLLAMA_BASE_URL` is needed for enrichment.

## Run the API

```bash
uv run uvicorn app.main:app --reload
```

- API: http://localhost:8000
- Interactive docs: http://localhost:8000/docs
- Email inbox (Mailpit): http://localhost:8025

## Endpoints

| Endpoint | Login | Description | Returns |
| --- | --- | --- | --- |
| `GET /health/live` | No | The process is running | Always `200` |
| `GET /health/ready` | No | Postgres and Redis respond within 2 seconds | `200` if both are OK, `503` if either fails |
| `POST /auth/signup` | No | Start sign-up with an email and password (8–128 characters) | Always `202`, or `422` if the input is invalid |
| `POST /auth/verify-email` | No | Confirm an email with the token from the sign-up email | `200`, or `400` if the token is invalid, used, or expired |
| `POST /auth/login` | No | Log in with email and password; sets the session cookie | `200` with the user, or `401` |
| `POST /auth/logout` | No | End the current session and clear the cookie | Always `204` |
| `GET /auth/me` | Yes | The logged-in user | `200` with the user, or `401` |
| `GET /topics` | No | All topics | `200` with the list |
| `GET /me/interests` | Yes | The user's chosen topics | `200` with the list |
| `PUT /me/interests` | Yes | Replace the user's interests (3–15 topic IDs, no duplicates) | `200`, `400` for unknown topics, or `422` |
| `POST /hop` | Yes | A random unseen page from the user's interests; records a view | `200` with the page, `409` without interests, or `404` when everything has been seen |
| `PUT /pages/{page_id}/reaction` | Yes | Like or dislike a page Hop has shown the user (`{"reaction": "like"}` or `"dislike"`) | `200`, `404` if the page wasn't shown to the user, or `422` |
| `GET /me/likes` | Yes | Pages the user currently likes, newest first | `200` with the list |

## Sign-up flow

Sign-up always returns the same response, `202` with "Check your email to finish signing up.", so nobody can use it to find out which emails have accounts. What happens next depends on the email:

| Situation | What the server does | Email sent |
| --- | --- | --- |
| New email | Creates an unverified user | A confirmation link |
| Existing, unverified | Replaces the password | A new confirmation link |
| Existing, verified | Changes nothing | "You already have an account" |

Details:

- Passwords are hashed with Argon2id. Plain passwords are never stored.
- The password is always hashed, and emails are sent after the response, so response times don't reveal which case happened.
- Verification tokens are random (256 bits), stored in Redis only as SHA-256 hashes, expire after 24 hours, and work once.
- The email link opens a frontend page that sends a `POST` to `/auth/verify-email`, so email scanners that open links can't use up the token.

## Login and sessions

Logging in creates a random session token. Redis stores the token's SHA-256 hash with the user's ID for 7 days, and the browser receives the token in a cookie.

| Cookie setting | Purpose |
| --- | --- |
| `HttpOnly` | JavaScript can't read the cookie, so injected scripts (XSS) can't steal the session |
| `Secure` | HTTPS only, in production (`COOKIE_SECURE=true`) |
| `SameSite=Lax` | Not sent on cross-site `POST` requests, which blocks CSRF |

- Every login failure (unknown email, wrong password, unverified account) returns the same `401` and message, and unknown emails are checked against a dummy hash, so login can't reveal which emails have accounts.
- Logging out deletes the session from Redis, so the token stops working immediately.
- Password hashes made with older Argon2 settings are upgraded on the next successful login.
- Protected endpoints use the `CurrentUserDep` dependency, which responds `401` without a valid session.

Not yet implemented: rate limiting for login attempts.

## Hopping

Users choose 3–15 topics as interests. Each `POST /hop` picks a random **approved** page that belongs to at least one of those topics and that the user hasn't seen, then records a `view` in the `interactions` table.

- `POST` is used instead of `GET` because each hop changes data (it records a view), and `GET` requests must not change anything.
- Pages are picked with `ORDER BY random()`, a simple baseline that works well for thousands of pages. The recommender will replace it.

### Likes and dislikes

`interactions` is an append-only log: rows are added, never changed. A user's current reaction to a page is their most recent `like` or `dislike`, so changing a like to a dislike adds a new row, and the full history stays available for the recommender. `GET /me/likes` finds each page's latest reaction with Postgres's `DISTINCT ON` and returns the pages whose latest reaction is a like.

Users can only react to pages Hop has shown them. A page that wasn't shown and a page that doesn't exist get the same `404`, so the endpoint doesn't reveal which page IDs exist.

### Showing pages in an iframe

The frontend shows each page inside an iframe, but many sites forbid that with a response header. If a browser is told no, it shows a blank frame and doesn't tell our JavaScript why. So the backend checks each page's headers ahead of time and stores the answer in `pages.embeddable`:

| Value | Meaning | What the frontend shows |
| --- | --- | --- |
| `true` | The site allows iframes | The page in an iframe |
| `false` | The site forbids iframes | A card with an "Open in new tab" button |
| `null` | Not checked yet, or the page couldn't be loaded | The iframe, plus a hint to open it in a new tab if it stays blank |

`make check-embeds` (`scripts/check_embeddable.py`) fetches every page whose value is `null`, 5 at a time, with the `HopBot` user agent, and saves the result. Run it after `make seed` or after adding pages. The rules live in `app/services/embeds.py`, the same rules browsers use:

1. If `Content-Security-Policy` has a `frame-ancestors` directive, it decides alone (browsers then ignore `X-Frame-Options`). Hop is an unknown site to them, so only `*` allows it.
2. Otherwise, any `X-Frame-Options` value (`DENY`, `SAMEORIGIN`) blocks other sites.
3. `Content-Security-Policy-Report-Only` only reports problems and never blocks, so it's ignored.

A site can change its headers later; set `embeddable` back to `NULL` to check a page again.

### Starter pages

`make seed` loads the pages listed in `scripts/seed_pages.json` (3 per topic) as `approved`, since they're hand-picked. It skips URLs that already exist, so it's safe to run again. To add pages, add entries to the JSON file with a URL, title, summary, and topic slugs.

## Ingestion pipeline

The ingestion pipeline turns a list of URLs into stored pages, in the background. The API and the worker share the database and Redis but run as separate processes.

```bash
make worker                    # terminal 1: start the worker
make ingest                    # terminal 2: queue scripts/sources.txt
make ingest f=my-list.txt      # or your own list (one URL per line, # for comments)
```

For each URL, the worker (`app/ingestion/pipeline.py`):

1. **Normalizes the URL** (`urls.py`): lowercase host, no default port, no `#fragment`, no tracking parameters (`utm_*`, `fbclid`, ...), sorted query. Skips it if that URL is already stored.
2. **Fetches it safely** (`fetch.py`), checking every redirect hop:
    - **SSRF protection** (`network.py`): refuses hosts that resolve to private, loopback, link-local (including the cloud metadata address `169.254.169.254`), or other non-public addresses.
    - **robots.txt**: obeys the site's rules for `HopBot`, cached in Redis for 24 hours. A missing file (4xx) allows everything; an unreachable one (5xx) blocks everything ([RFC 9309](https://www.rfc-editor.org/rfc/rfc9309)).
    - **Politeness** (`politeness.py`): at most one request per site every `CRAWL_DELAY_SECONDS`, enforced through Redis, so it holds across workers.
    - **Limits**: 5 redirects, 2 MB per page, HTML only.
3. **Extracts the article** (`extract.py`) with trafilatura: main text and title, without menus and footers. Pages under 200 words are skipped.
4. **Checks for duplicates**: the page's own `<link rel="canonical">` (trusted only on the same site), then **SimHash** (`simhash.py`) for near-duplicates such as the same article on another URL.
5. **Stores it as `pending`**, with the text, word count, fingerprint, and whether it can be shown in an iframe, then queues it for enrichment (below). Hop only shows `approved` pages.

| Outcome | Meaning |
| --- | --- |
| `added` | Stored as a pending page |
| `duplicate` | The same URL (or its canonical URL) is already stored |
| `near_duplicate` | The same text is already stored under another URL |
| `invalid_url` / `unsafe_url` | Not an http(s) URL / points to a private address |
| `blocked_by_robots` | The site's robots.txt asks us not to fetch it |
| `fetch_failed` | 4xx response, unknown host, or still failing after retries |
| `not_html` / `no_content` / `too_short` | Not a web page, no readable text, or under 200 words |

Timeouts, network errors, `429`, and `5xx` responses are retried twice, after 10 and 60 seconds. Jobs go through a Redis Stream, so a job is only removed once a worker finishes it; results are kept in Redis for 7 days.

**Page statuses:** `pending` (fetched, not enriched yet), `approved` (shown by Hop), `rejected`, `needs_review` (for the curator agent or a person), and `dead` (stopped working). `pages.status_reason` records why.

### How near-duplicate detection works

SimHash gives each text a 64-bit fingerprint where similar texts get similar fingerprints. Hop treats fingerprints that differ in 7 bits or fewer as the same article. Copies with a different heading or footer land around 6 bits apart; unrelated articles land around 32.

To avoid comparing against every stored page, each fingerprint is split into 8 bands of 8 bits, stored in `pages.simhash_bands` with a GIN index. Two fingerprints within 7 bits of each other must share at least one identical band (pigeonhole principle), so Postgres only returns pages that share a band (`&&`), and only those are compared bit by bit.

Known limits: two near-duplicates processed at the same moment by different workers can both be stored, and the SSRF check doesn't yet protect against DNS rebinding (see `network.py`).

### Enrichment

After a page is stored, the worker's `enrich_page` task (`app/ingestion/enrich.py`) decides whether Hop shows it:

1. **Safety screen** (`safety.py`): the domain blocklist in `app/ingestion/blocked_domains.txt` (subdomains included), then [Google Safe Browsing](https://developers.google.com/safe-browsing/reference/rest) (the v4 Lookup API, `threatMatches:find`, which answers in JSON; v5's `urls:search` only answers in protobuf). A blocked or flagged page is rejected right away, without an LLM call.
2. **One LLM call** returns JSON matching a schema: a 2-sentence summary, up to 3 topics from Hop's 15 (each with a confidence), a quality score from 0 to 1, spam and adult flags, and a one-line reason. The page text is fenced in `<page_content>` tags, and the instructions say to ignore anything written inside it (prompt injection). Every answer is validated with Pydantic.
3. **Embedding** (`app/ai/embeddings.py`): Voyage `voyage-4-lite`, 1,024 numbers per page, stored in `pages.embedding` (pgvector, HNSW index) for the recommender.
4. **Routing rules** (plain code, in order):

| Check | Result |
| --- | --- |
| Blocklisted or flagged by Safe Browsing | `rejected` |
| Adult content or spam | `rejected` |
| Quality below 0.3 | `rejected` |
| No topic with confidence 0.6 or more | `needs_review` |
| Safe Browsing not configured | `needs_review` |
| Quality below 0.6 | `needs_review` |
| Everything else | `approved` |

Topics with confidence 0.6 or more (up to 3) are saved in `page_topics` with their confidence. Rejected pages aren't embedded.

**LLM failover** (`app/ai/llm.py`): Gemini, OpenAI, and Ollama all speak the OpenAI chat completions protocol, so one small client handles all three. Providers are tried in that order. A provider that answers `429` goes on a Redis cooldown (its `Retry-After`, or 60 seconds) and is skipped until then; any other failure, including an answer that doesn't match the schema, moves on to the next. Embeddings have no fallback on purpose: vectors from different models can't be compared.

If a service is down, the task retries after 30 seconds and 5 minutes. After that the page stays `pending`; `make enrich` queues every pending page that hasn't been enriched.

### Enrichment API keys

Put keys in the root `.env` (never commit it), then restart the worker. All have free options:

| Key | Where to get it | Notes |
| --- | --- | --- |
| `GEMINI_API_KEY` | [Google AI Studio](https://aistudio.google.com/) → Get API key | Free tier with rate limits; failover handles `429`s |
| `VOYAGE_API_KEY` | [Voyage AI dashboard](https://dashboard.voyageai.com/) → API keys | Free token allowance, then paid per token |
| `SAFE_BROWSING_API_KEY` | [Google Cloud console](https://console.cloud.google.com/): enable the Safe Browsing API, then create an API key restricted to it | Non-commercial use only; commercial use needs the Web Risk API |
| `OPENAI_API_KEY` (optional) | [OpenAI platform](https://platform.openai.com/) | Paid |
| `OLLAMA_BASE_URL` (optional) | Install [Ollama](https://ollama.com/), run `ollama pull llama3.2` | Free, runs on your machine |

### Link-rot checks

Pages break over time: they move, disappear, or their domain expires and turns into an ad page. `app/ingestion/linkrot.py` re-checks every approved page, using the same safe fetcher as ingestion (SSRF checks, robots.txt, politeness).

```bash
make worker         # terminal 1
make scheduler      # terminal 2: queues the check every day at 03:00 UTC
make check-links    # or run it right now
```

The scheduler (taskiq's `TaskiqScheduler`) reads the `schedule` label on the `check_links` task and queues it daily. Run only one scheduler; two would queue every check twice. The task finds up to 200 approved pages that are due (`next_check_at` has passed, or never checked), oldest first, and queues one `recheck_page` job each.

| Result of the check | What happens |
| --- | --- |
| Page loads with a readable article | Next check in 30 days; failure count reset; iframe support updated |
| Temporary trouble (timeout, 404, 5xx, no readable text) | Failure count +1; try again tomorrow |
| 3 failures in a row | `dead` |
| `410 Gone`, robots.txt now blocks Hop, or a private address | `dead` right away |
| Now redirects to a different site (`www.` doesn't count) | `needs_review` |
| Text changed by more than 24 of 64 SimHash bits | `needs_review` (for example, a parked domain) |

Newly approved pages get their first check 30 days after enrichment. Hand-picked seed pages are fingerprinted on their first check. Hop only shows `approved` pages, so dead pages simply stop appearing.

## Database migrations

Migrations are managed with [Alembic](https://alembic.sqlalchemy.org/) and live in `migrations/versions/`.

```bash
uv run alembic upgrade head                                 # apply all migrations
uv run alembic revision --autogenerate -m "describe change" # generate from model changes
uv run alembic downgrade -1                                 # undo the last migration
```

Always review an autogenerated migration before applying it. Never edit a migration that has already run on a shared database; add a new one instead.

## Tests and linting

```bash
uv run pytest
uv run ruff check --fix .
uv run ruff format .
```

The iframe checker, crawler, and enrichment tests use fake servers (`tests/web.py` and `httpx.MockTransport`), so they never touch the network or need API keys. Tests run against a real Postgres database (`TEST_DATABASE_URL`), so Postgres must be running. All migrations are applied to the test database at the start of each run, and users and pages are emptied after each test. Redis and email are replaced with in-memory fakes, so tests never send real email.

## Project structure

```
app/
├── main.py              # App setup, lifespan, routers
├── config.py            # Settings loaded from the root .env
├── db.py                # Postgres engine and session factory
├── cache.py             # Redis client
├── dependencies.py      # Shared dependencies (database, Redis, email, current user)
├── worker.py            # Background worker and scheduler (taskiq)
├── email.py             # Email sending (SMTP)
├── security.py          # Password hashing (Argon2) and token helpers
├── ai/                  # AI service clients
│   ├── llm.py           # JSON from chat models, with failover
│   └── embeddings.py    # Voyage embeddings
├── ingestion/           # Ingestion pipeline
│   ├── pipeline.py      # The steps for one URL, and retries
│   ├── linkrot.py       # Re-checks approved pages, retires broken ones
│   ├── enrich.py        # LLM analysis, embedding, and routing rules
│   ├── safety.py        # Blocklist and Safe Browsing
│   ├── blocked_domains.txt  # Domains never stored
│   ├── urls.py          # URL normalization
│   ├── network.py       # SSRF protection
│   ├── fetch.py         # Safe fetching: redirects, robots.txt, size limits
│   ├── politeness.py    # One request per site at a time
│   ├── extract.py       # Article text, title, canonical link
│   └── simhash.py       # Near-duplicate fingerprints
├── models/              # SQLAlchemy models (tables)
│   ├── base.py          # Base class and constraint naming convention
│   ├── associations.py  # page_topics and user_interests link tables
│   ├── interaction.py   # Views, likes, and dislikes
│   ├── page.py
│   ├── topic.py
│   └── user.py
├── schemas/             # Request and response shapes
│   ├── auth.py
│   ├── pages.py
│   ├── reactions.py
│   └── topics.py
├── services/            # Business logic
│   ├── auth.py          # Sign-up, email verification, and login
│   ├── embeds.py        # Whether a page allows being shown in an iframe
│   ├── hop.py           # Picking the next page
│   ├── reactions.py     # Likes, dislikes, and the likes list
│   ├── sessions.py      # Session tokens in Redis
│   └── topics.py        # Topics and interests
└── routers/             # Endpoints
    ├── auth.py
    ├── health.py
    ├── hop.py
    ├── interests.py
    ├── reactions.py
    └── topics.py
migrations/
└── versions/            # Migration files, applied in order
scripts/
├── check_embeddable.py  # Checks unchecked pages for iframe support
├── check_links.py       # Runs the link check now
├── enqueue_enrichment.py  # Queues pending pages for enrichment
├── enqueue_urls.py      # Queues a URL list for the worker
├── sources.txt          # Sample URLs for make ingest
├── seed_pages.json      # Starter pages
└── seed_pages.py        # Loads the starter pages
tests/
├── conftest.py          # Test database, fakes, test clients
├── test_auth.py         # Sign-up and email verification
├── test_embeds.py       # Iframe header rules
├── test_embeddings.py   # Voyage client
├── test_enrich.py       # Routing rules and enrichment
├── test_linkrot.py      # Link checks: due pages, failures, dead, changed
├── test_llm.py          # Provider failover and cooldowns
├── test_safety.py       # Blocklist and Safe Browsing
├── test_fetch.py        # Redirects, robots.txt, limits, politeness
├── test_network.py      # SSRF address checks
├── test_pipeline.py     # Ingestion outcomes and retries
├── test_simhash.py      # Fingerprints and the band guarantee
├── test_urls.py         # URL normalization
├── web.py               # A fake internet for crawler tests
├── test_health.py
├── test_hop.py
├── test_interests.py
├── test_reactions.py    # Likes, dislikes, and the likes list
├── test_security.py
├── test_sessions.py     # Login, logout, and the current user
└── test_topics.py
```