# syntax=docker/dockerfile:1

# The Hop API image. The worker and scheduler use it too, with another command:
#   docker run hop-api taskiq worker app.worker:broker
# Settings come from environment variables (see the backend README); no .env
# file is copied into the image.

# --- Build: install the locked dependencies into /app/.venv ------------------
FROM python:3.12-slim AS build

COPY --from=ghcr.io/astral-sh/uv:0.8.17 /uv /bin/uv

# Precompile .pyc files for a faster start; copy (not link) from uv's cache;
# use the image's Python, never a downloaded one
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0

WORKDIR /app

# Dependencies first, in their own layer, so a code change doesn't reinstall them
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-dev --no-install-project

COPY . .
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev


# --- Runtime: just Python, the virtualenv, and the code ----------------------
FROM python:3.12-slim

# A user without a home or a shell login; the app never runs as root
RUN groupadd --system --gid 10001 hop \
    && useradd --system --uid 10001 --gid hop --no-create-home --shell /usr/sbin/nologin hop

WORKDIR /app
# Owned by root and only readable by the app, so a compromised process can't
# rewrite its own code
COPY --from=build /app /app

# FORWARDED_ALLOW_IPS: uvicorn trusts X-Forwarded-For only from these
# addresses. Set it to the reverse proxy's address in production, so the rate
# limits see real clients instead of the proxy.
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    FORWARDED_ALLOW_IPS=127.0.0.1

USER hop
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/live', timeout=2)"]

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
