# Hop Backend

FastAPI service for Hop. It serves the API, connects to Postgres (with pgvector) and Redis, handles sign-up with email verification and login with server-side sessions, and exposes health checks.

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

## Run the API

```bash
uv run uvicorn app.main:app --reload
```

- API: http://localhost:8000
- Interactive docs: http://localhost:8000/docs
- Email inbox (Mailpit): http://localhost:8025

## Endpoints

| Endpoint | Description | Returns |
| --- | --- | --- |
| `GET /health/live` | The process is running | Always `200` |
| `GET /health/ready` | Postgres and Redis respond within 2 seconds | `200` if both are OK, `503` if either fails |
| `POST /auth/signup` | Start sign-up with an email and password (8–128 characters) | Always `202`, or `422` if the input is invalid |
| `POST /auth/verify-email` | Confirm an email with the token from the sign-up email | `200`, or `400` if the token is invalid, used, or expired |
| `POST /auth/login` | Log in with email and password; sets the session cookie | `200` with the user, or `401` |
| `POST /auth/logout` | End the current session and clear the cookie | Always `204` |
| `GET /auth/me` | The logged-in user | `200` with the user, or `401` |

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
uv run ruff check .
uv run ruff format .
```

Tests run against a real Postgres database (`TEST_DATABASE_URL`), so Postgres must be running. All migrations are applied to the test database at the start of each run, and the `users` table is emptied after each test. Redis and email are replaced with in-memory fakes, so tests never send real email.

## Project structure

```
app/
├── main.py              # App setup, lifespan, routers
├── config.py            # Settings loaded from the root .env
├── db.py                # Postgres engine and session factory
├── cache.py             # Redis client
├── dependencies.py      # Shared dependencies (database, Redis, email, current user)
├── email.py             # Email sending (SMTP)
├── security.py          # Password hashing (Argon2) and token helpers
├── models/              # SQLAlchemy models (tables)
│   ├── base.py          # Base class and constraint naming convention
│   ├── topic.py
│   └── user.py
├── schemas/
│   └── auth.py          # Request and response shapes for auth endpoints
├── services/
│   ├── auth.py          # Sign-up, email verification, and login logic
│   └── sessions.py      # Session tokens in Redis
└── routers/
    ├── auth.py          # Auth endpoints
    └── health.py        # Health check endpoints
migrations/
└── versions/            # Migration files, applied in order
tests/
├── conftest.py          # Test database, fake email, fake Redis, test client
├── test_auth.py         # Sign-up and email verification
├── test_health.py
├── test_security.py
└── test_sessions.py     # Login, logout, and the current user
```