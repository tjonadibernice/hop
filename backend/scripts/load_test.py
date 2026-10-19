"""Load test for POST /hop: many users hopping at once, with latency percentiles.

It never touches your dev data. It uses its own database (hop_loadtest, on the
same Postgres server) and Redis database 15, and empties both on every run.

What it does:
1. Creates hop_loadtest if needed and applies the migrations.
2. Seeds fake approved pages (with random embeddings) and users. Each user has
   3 interests and 12 reactions, so the recommender uses the taste vector,
   which is the slowest way to pick a page.
3. Starts the API (uvicorn) and a worker against that database and Redis.
4. Each simulated user hops, sometimes likes or dislikes the page, waits a
   moment, and hops again, until time is up.
5. Prints p50/p95/p99 latency, how many hops came from the queue, and whether
   p95 met the target. The exit code is 1 if it didn't.

Usage, from backend/:
    uv run python -m scripts.load_test               # with the hop queue
    uv run python -m scripts.load_test --no-queue    # every page picked live
    uv run python -m scripts.load_test --users 100 --seconds 60
    uv run python -m scripts.load_test --api-workers 4   # more API processes

Remove the database afterwards with:  DROP DATABASE hop_loadtest;
"""

import argparse
import asyncio
import math
import os
import random
import statistics
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
from alembic import command
from alembic.config import Config
from redis.asyncio import Redis
from sqlalchemy import insert, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import settings
from app.models import (
    EMBEDDING_DIMENSIONS,
    Interaction,
    Page,
    Topic,
    User,
    page_topics,
    user_interests,
)
from app.services import sessions

BACKEND_DIR = Path(__file__).resolve().parents[1]
DATABASE_NAME = "hop_loadtest"
REDIS_DB = 15
PORT = 8765
REACTIONS_PER_USER = 12  # above the recommender's cold-start threshold (10)


def loadtest_urls() -> tuple[str, str]:
    database_url = make_url(settings.database_url).set(database=DATABASE_NAME)
    redis_url = httpx.URL(settings.redis_url).copy_with(path=f"/{REDIS_DB}")
    return database_url.render_as_string(hide_password=False), str(redis_url)


async def create_database() -> None:
    engine = create_async_engine(settings.database_url, isolation_level="AUTOCOMMIT")
    async with engine.connect() as conn:
        exists = await conn.scalar(
            text("SELECT 1 FROM pg_database WHERE datname = :name"),
            {"name": DATABASE_NAME},
        )
        if not exists:
            await conn.execute(text(f'CREATE DATABASE "{DATABASE_NAME}"'))
    await engine.dispose()


def migrate(database_url: str) -> None:
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.attributes["database_url"] = database_url
    command.upgrade(config, "head")


def unit_vector(rng: random.Random) -> list[float]:
    vector = [rng.gauss(0, 1) for _ in range(EMBEDDING_DIMENSIONS)]
    length = math.sqrt(sum(value * value for value in vector))
    return [value / length for value in vector]


async def seed(
    database_url: str, redis: Redis, pages: int, users: int, rng: random.Random
) -> list[str]:
    """Fresh pages and users. Returns one session token per user."""
    engine = create_async_engine(database_url)
    now = datetime.now(UTC)
    async with engine.begin() as conn:
        await conn.execute(text("TRUNCATE users, pages CASCADE"))
        topic_ids = list(await conn.scalars(select(Topic.id)))

        page_rows = []
        topic_rows = []
        for number in range(pages):
            page_id = uuid.uuid4()
            url = f"https://loadtest.example/{number}"
            page_rows.append(
                {
                    "id": page_id,
                    "url": url,
                    "canonical_url": url,
                    "title": f"Load test page {number}",
                    "summary": "A page made up for the load test.",
                    "status": "approved",
                    "embeddable": True,
                    "quality_score": rng.uniform(0.6, 1.0),
                    "embedding": unit_vector(rng),
                }
            )
            for topic_id in rng.sample(topic_ids, rng.choice((1, 2))):
                topic_rows.append({"page_id": page_id, "topic_id": topic_id})
        for start in range(0, len(page_rows), 500):
            await conn.execute(insert(Page), page_rows[start : start + 500])
        await conn.execute(insert(page_topics), topic_rows)

        pages_by_topic: dict[int, list[uuid.UUID]] = {}
        for row in topic_rows:
            pages_by_topic.setdefault(row["topic_id"], []).append(row["page_id"])

        user_ids = []
        for number in range(users):
            user_id = uuid.uuid4()
            user_ids.append(user_id)
            await conn.execute(
                insert(User),
                {
                    "id": user_id,
                    "email": f"user{number}@loadtest.example",
                    "password_hash": "not-a-real-hash",
                    "email_verified_at": now,
                },
            )
            interests = rng.sample(topic_ids, 3)
            await conn.execute(
                insert(user_interests),
                [{"user_id": user_id, "topic_id": t} for t in interests],
            )
            candidates = {p for t in interests for p in pages_by_topic.get(t, [])}
            reacted = rng.sample(sorted(candidates), REACTIONS_PER_USER)
            rows = []
            for page_id in reacted:
                when = now - timedelta(days=rng.uniform(0, 60))
                kind = "like" if rng.random() < 0.6 else "dislike"
                rows.append(_interaction(user_id, page_id, "view", when))
                rows.append(_interaction(user_id, page_id, kind, when))
            await conn.execute(insert(Interaction), rows)
    await engine.dispose()

    await redis.flushdb()
    return [await sessions.create_session(redis, user_id) for user_id in user_ids]


def _interaction(user_id, page_id, kind, when) -> dict:
    strategy = "random" if kind == "view" else None
    return {
        "user_id": user_id,
        "page_id": page_id,
        "kind": kind,
        "strategy": strategy,
        "created_at": when,
    }


def start_services(database_url: str, redis_url: str, queue: bool, api_workers: int):
    env = {
        **os.environ,
        # Environment variables win over .env, so these only affect the
        # processes started here
        "DATABASE_URL": database_url,
        "REDIS_URL": redis_url,
        "HOP_QUEUE_ENABLED": "true" if queue else "false",
    }
    api = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--port",
            str(PORT),
            "--workers",
            str(api_workers),
            "--log-level",
            "warning",
        ],
        cwd=BACKEND_DIR,
        env=env,
    )
    worker = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "taskiq",
            "worker",
            "app.worker:broker",
            "--workers",
            "1",
            "--log-level",
            "WARNING",
        ],
        cwd=BACKEND_DIR,
        env=env,
    )
    return api, worker


async def wait_until_ready(base_url: str) -> None:
    async with httpx.AsyncClient(base_url=base_url) as client:
        for _ in range(60):
            try:
                if (await client.get("/health/ready")).status_code == 200:
                    return
            except httpx.TransportError:
                pass
            await asyncio.sleep(0.5)
    raise SystemExit("The API didn't start. Check the output above.")


@dataclass
class Results:
    latencies_ms: list[float] = field(default_factory=list)
    server_ms: list[float] = field(default_factory=list)  # from Server-Timing
    sources: dict[str, int] = field(default_factory=dict)
    statuses: dict[int, int] = field(default_factory=dict)


async def simulate_user(
    client: httpx.AsyncClient,
    deadline: float,
    think_ms: tuple[int, int],
    results: Results,
    rng: random.Random,
) -> None:
    while time.perf_counter() < deadline:
        started = time.perf_counter()
        response = await client.post("/hop")
        elapsed_ms = (time.perf_counter() - started) * 1000
        results.statuses[response.status_code] = (
            results.statuses.get(response.status_code, 0) + 1
        )
        if response.status_code == 404:
            return  # this user has seen everything
        if response.status_code == 200:
            results.latencies_ms.append(elapsed_ms)
            timing = response.headers.get("Server-Timing", "")
            if "dur=" in timing:
                results.server_ms.append(float(timing.split("dur=")[1]))
            source = response.headers.get("X-Hop-Source", "?")
            results.sources[source] = results.sources.get(source, 0) + 1
            if rng.random() < 0.3:
                reaction = "like" if rng.random() < 0.6 else "dislike"
                await client.put(
                    f"/pages/{response.json()['id']}/reaction",
                    json={"reaction": reaction},
                )
        await asyncio.sleep(rng.uniform(*think_ms) / 1000)


async def warm_up(clients: list[httpx.AsyncClient]) -> None:
    """One untimed hop per user.

    It opens each user's connection (so connection setup isn't counted as
    hop latency) and starts filling the queues, like returning users.
    """
    for client in clients:
        await client.post("/hop")


def percentile(values: list[float], pct: int) -> float:
    return statistics.quantiles(values, n=100, method="inclusive")[pct - 1]


def report(results: Results, seconds: float, target_ms: float, queue: bool) -> bool:
    latencies = results.latencies_ms
    if len(latencies) < 2:
        print("Not enough successful hops to report.")
        return False
    p95 = percentile(latencies, 95)
    hops = len(latencies)
    from_queue = results.sources.get("queue", 0)
    print()
    print(f"Hop queue:       {'on' if queue else 'off'}")
    print(f"Hops:            {hops} in {seconds:.0f}s ({hops / seconds:.1f}/s)")
    print(f"Status codes:    {dict(sorted(results.statuses.items()))}")
    print(f"From the queue:  {from_queue / hops:.0%}")
    print(f"p50:             {percentile(latencies, 50):.1f} ms")
    print(f"p95:             {p95:.1f} ms   (target {target_ms:.0f} ms)")
    print(f"p99:             {percentile(latencies, 99):.1f} ms")
    print(f"max:             {max(latencies):.1f} ms")
    if len(results.server_ms) >= 2:
        # Time inside the app only; the rest is waiting for the event loop,
        # the CPU, or the network
        print(
            f"Inside the app:  p50 {percentile(results.server_ms, 50):.1f} ms, "
            f"p95 {percentile(results.server_ms, 95):.1f} ms"
        )
    passed = p95 <= target_ms
    print("PASS" if passed else "FAIL")
    return passed


async def run(args: argparse.Namespace) -> bool:
    database_url, redis_url = loadtest_urls()
    redis = Redis.from_url(redis_url, decode_responses=True)
    rng = random.Random(args.seed)
    print(f"Seeding {args.pages} pages and {args.users} users...")
    tokens = await seed(database_url, redis, args.pages, args.users, rng)
    await redis.aclose()

    api, worker = start_services(database_url, redis_url, args.queue, args.api_workers)
    base_url = f"http://127.0.0.1:{PORT}"
    clients = [
        httpx.AsyncClient(
            base_url=base_url,
            cookies={settings.session_cookie_name: token},
            timeout=30,
        )
        for token in tokens
    ]
    try:
        await wait_until_ready(base_url)
        await warm_up(clients)
        await asyncio.sleep(3)  # let the first refills finish

        print(f"Running {args.users} users for {args.seconds}s...")
        results = Results()
        deadline = time.perf_counter() + args.seconds
        started = time.perf_counter()
        await asyncio.gather(
            *(
                simulate_user(
                    client,
                    deadline,
                    (args.think_min_ms, args.think_max_ms),
                    results,
                    random.Random(rng.random()),
                )
                for client in clients
            )
        )
        return report(
            results, time.perf_counter() - started, args.target_p95_ms, args.queue
        )
    finally:
        for client in clients:
            await client.aclose()
        for process in (api, worker):
            process.terminate()
        for process in (api, worker):
            process.wait(timeout=15)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--users", type=int, default=30)
    parser.add_argument("--seconds", type=int, default=30)
    parser.add_argument("--pages", type=int, default=3000)
    parser.add_argument("--think-min-ms", type=int, default=200)
    parser.add_argument("--think-max-ms", type=int, default=1000)
    parser.add_argument("--target-p95-ms", type=float, default=100)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--api-workers", type=int, default=1, help="uvicorn worker processes"
    )
    parser.add_argument(
        "--no-queue",
        dest="queue",
        action="store_false",
        help="pick every page while the user waits (for comparison)",
    )
    args = parser.parse_args()

    asyncio.run(create_database())
    migrate(loadtest_urls()[0])  # alembic runs its own event loop
    passed = asyncio.run(run(args))
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
