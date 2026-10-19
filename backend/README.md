# Hop Backend

FastAPI service for Hop. It serves the API, connects to Postgres (with pgvector) and Redis, handles sign-up with email verification and login with server-side sessions, stores users' interests, serves pages through the Hop endpoint, and records likes and dislikes. A background worker runs the ingestion pipeline, which fetches, cleans, and deduplicates new pages, then enriches them with an LLM and embeddings and decides which ones Hop shows. Daily scheduled jobs re-check approved pages, retire the ones that broke, and find new pages from RSS/Atom feeds and from the links inside approved pages.

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
| `REDIS_URL` | Yes | | Redis connection (sessions, verification tokens, hop queues, and worker jobs) |
| `TEST_DATABASE_URL` | For tests | | Separate Postgres database used by the tests |
| `SMTP_HOST` | No | `localhost` | Email server (Mailpit locally) |
| `SMTP_PORT` | No | `1025` | Email server port |
| `MAIL_FROM` | No | `Hop <no-reply@hop.local>` | Sender of outgoing emails |
| `APP_BASE_URL` | No | `http://localhost:5173` | Frontend address, used for links in emails |
| `SESSION_COOKIE_NAME` | No | `hop_session` | Name of the session cookie |
| `SESSION_TTL_SECONDS` | No | `604800` (7 days) | How long a login lasts |
| `COOKIE_SECURE` | No | `false` | Send the session cookie over HTTPS only; set to `true` in production |
| `RECOMMENDER_PERCENT` | No | `50` | Share of users (0–100) who get the recommender instead of random picks; the A/B split |
| `HOP_QUEUE_ENABLED` | No | `true` | Serve hops from each user's precomputed queue in Redis; `false` picks every page while the user waits |
| `CRAWLER_USER_AGENT` | No | `HopBot/0.1 (+https://github.com/tjonadibernice/hop)` | How the crawler identifies itself to websites |
| `CRAWL_DELAY_SECONDS` | No | `1.0` | Minimum time between two requests to the same website |
| `CRAWL_ALLOW_PRIVATE_HOSTS` | No | `false` | Lets the crawler fetch localhost and private addresses. Only for local testing |
| `GEMINI_API_KEY` | For enrichment | | First LLM provider (model `GEMINI_MODEL`, default `gemini-3.1-flash-lite`) |
| `GEMINI_REQUESTS_PER_MINUTE` | No | none | Spaces Gemini calls evenly across all workers, to stay under the per-minute limit |
| `GEMINI_MAX_CALLS_PER_DAY` | No | `1000` | Budget guard: after this many calls in a UTC day, Gemini is skipped until midnight |
| `OPENAI_API_KEY` | No | | Second LLM provider (model `OPENAI_MODEL`, default `gpt-5.6-luna`) |
| `OPENAI_REQUESTS_PER_MINUTE` / `OPENAI_MAX_CALLS_PER_DAY` | No | none / `1000` | Same limits for OpenAI |
| `OLLAMA_BASE_URL` | No | | Third LLM provider, a local model, e.g. `http://localhost:11434/v1` (model `OLLAMA_MODEL`, default `llama3.2`) |
| `VOYAGE_API_KEY` | No | | Embeddings (model `VOYAGE_MODEL`, default `voyage-4-lite`); without it, pages have no embedding |
| `SAFE_BROWSING_API_KEY` | No | | Google Safe Browsing; without it, pages can't be auto-approved |
| `CURATOR_ENABLED` | No | `true` | Let the curator agent review `needs_review` pages; `false` leaves them all for a person |
| `CURATOR_MAX_TURNS` / `CURATOR_MAX_TOOL_CALLS` | No | `8` / `6` | Most model calls and tool lookups one review may use |

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
| `POST /hop` | Yes | The next unseen page from the user's interests (recommender or random, see below); records a view | `200` with the page and its `strategy`, `409` without interests, or `404` when everything has been seen |
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

Users choose 3–15 topics as interests. Each `POST /hop` picks an **approved** page from those topics that the user hasn't seen, then records a `view` in the `interactions` table, along with the strategy that picked it.

- `POST` is used instead of `GET` because each hop changes data (it records a view), and `GET` requests must not change anything.
- Two strategies run side by side as an A/B test (`app/services/experiments.py`): **random** (`ORDER BY random()`, the baseline) and the **recommender** (below).
- The response includes `strategy` (`"recommender"` or `"random"`), and the frontend shows it as **Picked for you** or **Random find**. Note that the label is part of what the A/B test measures: users see which kind of pick they got.
- Every response has a `Server-Timing: app;dur=12.3` header with the time the app spent on it (visible in the browser's Network tab). `POST /hop` also sends `X-Hop-Source: queue` or `live` (next section).

### The hop queue

Picking a page with the recommender takes several queries and some math (the taste vector), about 30 ms with nobody else around and much more when many users hop at once. So pages are picked **ahead of time** (`app/services/hop_queue.py`):

```
POST /hop ──► pop "hop:queue:{user}" (Redis list) ──► re-check the page ──► record the view
                 │ empty?                                 │ still approved, unseen,
                 ▼                                        │ and in the user's interests?
            pick live (as before)                         ▼
                                                  fewer than 4 left? ──► queue a refill job
                                                                          (worker picks up to 10)
```

- **Refills run in the worker** (`refill_hop_queue` in `app/worker.py`) on their own Redis stream, `hop:refill`, so a backlog of ingestion jobs can't hold them up. A lock (`SET NX`, 60 seconds) makes sure only one refill per user is queued at a time; the worker releases it when it finishes.
- **Batch picking:** `recommend_many()` computes the topic counts and the taste vector once for the whole batch, then picks pages one by one (each with its own Thompson draw), skipping pages already picked or queued.
- **Stale entries are skipped, not trusted:** a queued page may have been rejected, retired, shown in another tab, or picked for old interests. Each popped entry is checked with one query; stale ones are dropped. Changing interests also clears the queue.
- **Each entry remembers its strategy,** so the view is recorded with the strategy that actually picked the page.
- **Without a worker**, nothing breaks: the queue stays empty and every hop is picked live, just slower. Queues expire after 24 hours without use.

### Load test

`make loadtest` measures `POST /hop` under load. It never touches your dev data: it uses its own database (`hop_loadtest`, created on the same Postgres server) and Redis database 15, and empties both on every run.

1. Seeds 3,000 approved pages with random embeddings and 30 users with 3 interests and 12 reactions each (so the recommender uses the taste vector, its slowest path).
2. Starts the API (uvicorn) and a worker against them.
3. Each simulated user hops, likes or dislikes 30% of pages, waits 0.2–1 second, and hops again, for 30 seconds.
4. Reports throughput, p50/p95/p99 latency, how many hops came from the queue, and time spent inside the app (from `Server-Timing`). Exits with code 1 if p95 is over 100 ms.

```bash
make loadtest                              # with the queue
make loadtest args="--no-queue"            # every page picked live
make loadtest args="--users 60 --api-workers 2"
```

Results on a laptop (WSL 2), with everything on one machine (Postgres, Redis, API, worker, and the load generator) and 30 users:

| | Hops/s | p50 | p95 | p99 | Inside the app (p95) | Result |
| --- | --- | --- | --- | --- | --- | --- |
| Queue on | 46.6 | 17 ms | 37 ms | 350 ms | 32 ms | Pass |
| Queue off | 42.7 | 58 ms | 208 ms | 489 ms | 200 ms | Fail |

The queue cuts p95 by about 5.5 times. Without it, almost all of a hop's time is the recommender running while the user waits ("inside the app" is nearly the whole latency); with it, a hop is a few fast lookups by primary key. The rare slow p99 requests come from the machine being shared: the load generator and the worker compete with the API for the same CPU. On a small 2-vCPU cloud machine the same test gave p95 70 ms with the queue and 319 ms without. To remove the test database afterwards: `DROP DATABASE hop_loadtest;`

### Recommendations

`app/services/recommender.py` makes two decisions per hop:

1. **Which topic? Thompson sampling.** For each of the user's interests, Hop keeps a Beta(likes + 1, dislikes + 1) distribution, draws one random number from each, and tries topics from the highest draw down. A loved topic usually wins, but a topic with little data has a wide distribution, so it sometimes draws high and gets a turn. That's built-in exploration: Hop keeps learning and stays surprising.
2. **Which page in that topic? Nearest to the user's taste.** The taste vector is a weighted average of the embeddings of pages the user reacted to: likes add, dislikes subtract half as much, and reactions fade with a 30-day half-life. pgvector returns the 10 approved, unseen pages closest to it (cosine distance, HNSW index), and one is chosen with weights 1, 1/2, 1/3, …, so closer pages are likelier but not certain.

**Cold start:** until a user has 10 reactions, there's no reliable taste, so pages in the chosen topic are ranked by their enrichment quality score instead. Pages without an embedding are still reachable: if the nearest-neighbor search finds nothing in a topic, Hop falls back to quality ranking.

**A/B test:** a hash of each user's ID puts them in bucket 0–99; buckets below `RECOMMENDER_PERCENT` get the recommender. The same user always gets the same strategy. `make ab-report` shows each group's users, views, likes, dislikes, and **liked rate** (views whose page the user currently likes), plus a two-proportion z-test that says whether the difference is real or could be chance:

```
Strategy      Users   Views  Likes  Dislikes  Liked rate
random           25    1000    156       844      15.6%
recommender      25    1000    636       364      63.6%

Difference: +48.0% (z = 21.95, p = 0.000): a real difference (p < 0.05)
```

(That example comes from a simulation with synthetic users who like pages close to a hidden taste, used to check the algorithm end to end. Real users will show smaller differences.)

**Embeddings for older pages:** pages approved by enrichment are embedded automatically. The hand-picked seed pages aren't, so run `make embed` once (it needs `VOYAGE_API_KEY`); it embeds every approved page that has no embedding yet, 64 at a time.

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

**Pacing and budget** (optional, per provider): `*_REQUESTS_PER_MINUTE` spaces calls one every 60/N seconds through a Redis key shared by all workers, so a burst of new pages waits its turn instead of triggering `429`s. `*_MAX_CALLS_PER_DAY` counts calls per UTC day in Redis (`llm:calls:{provider}:{date}`); past the cap, the provider is skipped until midnight, which protects a paid tier from a runaway day.

**Retries:** if a service fails, the task retries after 30 seconds and 5 minutes. When every provider is only cooling down, it waits for the cooldown instead (for example, 121 seconds for a `Retry-After: 120`). Waits over 15 minutes, such as a daily cap, don't hold the job open: the page stays `pending`, and the hourly `enrich_pending` job (at minute 15) queues pending pages that were never enriched. `make enrich` does the same right away. A Redis lock per page stops two jobs from enriching, and paying for, the same page.

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

The scheduler (taskiq's `TaskiqScheduler`) reads the `schedule` labels on the tasks: `poll_feeds` daily at 02:00 UTC, `check_links` daily at 03:00 UTC, `enrich_pending` every hour at minute 15, and `curate_pending` every hour at minute 45. Run only one scheduler; two would queue every check twice. The task finds up to 200 approved pages that are due (`next_check_at` has passed, or never checked), oldest first, and queues one `recheck_page` job each.

| Result of the check | What happens |
| --- | --- |
| Page loads with a readable article | Next check in 30 days; failure count reset; iframe support updated |
| Temporary trouble (timeout, 404, 5xx, no readable text) | Failure count +1; try again tomorrow |
| 3 failures in a row | `dead` |
| `410 Gone`, robots.txt now blocks Hop, or a private address | `dead` right away |
| Now redirects to a different site (`www.` doesn't count) | `needs_review` |
| Text changed by more than 24 of 64 SimHash bits | `needs_review` (for example, a parked domain) |

Newly approved pages get their first check 30 days after enrichment. Hand-picked seed pages are fingerprinted on their first check. Hop only shows `approved` pages, so dead pages simply stop appearing. A page sent to `needs_review` by a link check goes to the curator agent again, even if it reviewed the page before.

### Curator agent

Some pages can't be decided by the automatic rules: no confident topic, borderline quality, or a link check that found the page moved or changed. The curator agent (`app/curator/`) reviews them the way a careful editor would: it looks things up, then proposes **approve**, **reject**, or **escalate** (a person decides). It's built with [LangGraph](https://langchain-ai.github.io/langgraph/):

```
START -> agent -> tools  -> agent   (look something up, think again)
               -> submit -> END     (a decision)
               -> nudge  -> agent   (answered in prose: asked once to use a tool)
```

**Tools.** All read-only; the agent can't change anything directly.

| Tool | What it returns |
| --- | --- |
| `site_history` | How Hop judged other pages from the same site: counts by status, a few titles |
| `similar_pages` | The 5 nearest approved pages (pgvector), with their topics |
| `check_safety` | The blocklist and Safe Browsing result |
| `fetch_live_page` | Whether the page still loads, redirects to another site, or changed since it was stored (SimHash), plus a short excerpt |
| `submit_decision` | The final answer: decision, up to 3 topics, quality 0–1, reason |

**Guardrails** (`policy.py`) are plain code applied after the agent decides, so a page that talks the model into "approve" still can't get through:

| Rule | Result |
| --- | --- |
| Safe Browsing or the blocklist says unsafe | `rejected`, whatever the agent proposed |
| "approve" without a completed Safe Browsing check | `needs_review` (a person decides) |
| "approve" without a known topic, or with quality below 0.6 | `needs_review` |
| Turn limit (8 model calls) or no decision | `needs_review` |
| "reject" / "escalate" | `rejected` / `needs_review` |

**Prompt injection defenses.** Page text and anything from a tool that came from the web is wrapped in tags like `<page_content>`, and a closing tag inside the text is broken up so the page can't "end" the fence and pose as instructions. The system prompt says that text is data, and that a page trying to instruct the model is manipulative and should be rejected. The tools are read-only, and the guardrails decide.

**Limits.** At most 8 model calls and 6 tool lookups per review (`CURATOR_MAX_TURNS`, `CURATOR_MAX_TOOL_CALLS`), plus LangGraph's own recursion limit as a backstop. Model calls go through the same `LLMRouter` as enrichment (`LLMRouter.run`), so they share its failover, pacing, daily caps, and 429 cooldowns. When every provider is busy, the page simply stays waiting.

**Audit trail.** Every review adds a row to `curator_reviews`: what the agent proposed, the status Hop set, the guardrail that changed it (if any), topics, quality, provider, and every step (tool, arguments, the first 500 characters of the result). `pages.curated_at` records when the curator last looked; `needs_review` pages with a `curated_at` are the ones waiting for a person.

**When it runs.** Enrichment and link checks queue `curate_page` as soon as they send a page to review. `curate_pending` (hourly, at minute 45) queues up to 20 pages that were missed, and `make curate` queues all of them now. A lock stops two workers from reviewing the same page, and if a person or a link check changes the page's status while the agent is thinking, their decision stands. An approved page then shares its links, like any other.

The tool definitions use only the part of JSON Schema that Gemini accepts for tools (no `additionalProperties`, no empty objects); a test keeps it that way. When a provider refuses a request, the worker log shows its reason, for example `gemini: HTTP 400: ...`.

Without `SAFE_BROWSING_API_KEY`, the curator can still reject and escalate, but it can never approve. LangChain sends nothing to LangSmith unless you set `LANGSMITH_TRACING=true` yourself.

### Where new pages come from

| Source | How | `pages.source` |
| --- | --- | --- |
| Starter pages | `make seed` (approved without screening) | `seed` |
| Your URL lists | `make ingest` or `make ingest f=list.txt` | `manual` |
| RSS/Atom feeds | Daily at 02:00 UTC, or `make poll-feeds` | `feed` |
| Links in approved pages | Automatically, once per page | `link` |

Every source goes through the same pipeline: safe fetching, deduplication, screening, and link checks.

**Feeds** (`app/ingestion/feeds.py`): list feed URLs in `app/ingestion/feeds.txt`, one per line. To find a site's feed, look for an RSS icon or a "Subscribe" link, or search the page source for `application/rss+xml` or `application/atom+xml`; common addresses are `/feed`, `/rss`, `/atom.xml`, and `/index.xml`. The `poll_feeds` job queues one `poll_feed` job per feed. Each poll:

- fetches the feed with the safe fetcher (robots.txt, SSRF checks, politeness),
- sends `If-None-Match` / `If-Modified-Since` from the last poll (stored in Redis), so an unchanged feed answers `304 Not Modified` and costs the site almost nothing,
- reads RSS or Atom with [feedparser](https://pypi.org/project/feedparser/), takes the 20 newest posts from the last 30 days (posts without dates are kept), and queues the ones Hop doesn't have.

A broken feed is logged and tried again the next day; it doesn't stop the others.

**Link discovery** (`app/ingestion/discovery.py`): at ingestion, the links inside the article text (not menus or footers) are saved in `pages.outlinks`, up to 50. When a page is approved, or a seed page passes its first link check, its links are queued once (`links_queued_at`), with these limits:

| Limit | Value | Why |
| --- | --- | --- |
| Depth | Only `seed`, `manual`, and `feed` pages (depth 0) share links; pages found through links (depth 1) don't | Discovery stays one step away from pages a person or a feed chose, so it can't turn into an endless crawl |
| Links per page | 10, and at most 3 to any one site | One link-heavy page can't flood the queue |
| Pages per site | 50 in the library (`pages.site`, the host without `www.`) | No single site takes over |
| Skipped | Known pages, blocked domains, social and video sites, links to files (PDFs, images, archives) | They're not articles, or we already have them |

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
├── dependencies.py      # Shared dependencies (database, Redis, email, refills, current user)
├── timing.py            # Server-Timing header middleware
├── worker.py            # Background worker and scheduler (taskiq)
├── email.py             # Email sending (SMTP)
├── security.py          # Password hashing (Argon2) and token helpers
├── ai/                  # AI service clients
│   ├── llm.py           # JSON from chat models, with failover
│   └── embeddings.py    # Voyage embeddings
├── curator/             # The curator agent (LangGraph)
│   ├── tools.py         # Read-only tools and submit_decision
│   ├── prompts.py       # Instructions and the fenced page
│   ├── model.py         # Tool-calling model with provider failover
│   ├── graph.py         # The agent loop
│   ├── policy.py        # Guardrails that decide the final status
│   └── service.py       # One review, saved with its audit trail
├── ingestion/           # Ingestion pipeline
│   ├── pipeline.py      # The steps for one URL, and retries
│   ├── feeds.py         # RSS and Atom feeds
│   ├── feeds.txt        # Feeds to check daily
│   ├── discovery.py     # Queuing links from approved pages
│   ├── linkrot.py       # Re-checks approved pages, retires broken ones
│   ├── backfill.py      # Embeds pages that have no embedding
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
│   ├── curator.py       # curator_reviews: the agent's audit trail
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
│   ├── hop.py           # Picking the next page (A/B: random or recommender), queue refills
│   ├── hop_queue.py     # Each user's queue of ready pages in Redis
│   ├── recommender.py   # Thompson sampling and taste vectors
│   ├── experiments.py   # A/B assignment and the liked-rate report
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
├── ab_report.py         # Compares the A/B groups
├── load_test.py         # Load test for POST /hop
├── curate_pages.py      # Queues review pages for the curator
├── check_links.py       # Runs the link check now
├── embed_pages.py       # Embeds approved pages without an embedding
├── poll_feeds.py        # Checks the feeds now
├── enqueue_enrichment.py  # Queues pending pages for enrichment
├── enqueue_urls.py      # Queues a URL list for the worker
├── sources.txt          # Sample URLs for make ingest
├── seed_pages.json      # Starter pages
└── seed_pages.py        # Loads the starter pages
tests/
├── conftest.py          # Test database, fakes, test clients
├── test_auth.py         # Sign-up and email verification
├── test_embeds.py       # Iframe header rules
├── test_experiments.py  # A/B assignment, stats, z-test
├── test_hop_queue.py    # Queue refills, stale entries, refill requests
├── test_curator.py      # Guardrails, the agent loop, tools, injection, wire format
├── factories.py         # Helpers that create users, pages, reactions
├── test_embeddings.py   # Voyage client
├── test_enrich.py       # Routing rules and enrichment
├── test_discovery.py    # Article links, filters, caps, depth
├── test_feeds.py        # RSS/Atom parsing, conditional requests
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
├── test_recommender.py  # Thompson sampling, taste, candidates, backfill
├── test_security.py
├── test_sessions.py     # Login, logout, and the current user
└── test_topics.py
```