"""Background worker for the ingestion pipeline (taskiq + Redis Streams).

Run it with:  uv run taskiq worker app.worker:broker
Queue URLs with:  uv run python -m scripts.enqueue_urls scripts/sources.txt
"""

import logging
from dataclasses import asdict
from typing import Annotated, Any

import httpx
from taskiq import Context, TaskiqDepends, TaskiqEvents, TaskiqState
from taskiq_redis import RedisAsyncResultBackend, RedisStreamBroker

from app.cache import create_redis
from app.config import settings
from app.db import create_db_engine, create_session_factory
from app.ingestion.fetch import SafeFetcher
from app.ingestion.network import ensure_public_host
from app.ingestion.pipeline import ingest_with_retries

logger = logging.getLogger(__name__)

RESULT_TTL_SECONDS = 7 * 24 * 60 * 60

# Redis Streams keep a message until a worker acknowledges it, so a job isn't
# lost if a worker crashes halfway through
broker = RedisStreamBroker(
    url=settings.redis_url, queue_name="hop:ingest"
).with_result_backend(
    RedisAsyncResultBackend(settings.redis_url, result_ex_time=RESULT_TTL_SECONDS)
)


@broker.on_event(TaskiqEvents.WORKER_STARTUP)
async def startup(state: TaskiqState) -> None:
    """Create shared connections once per worker process, not once per job."""
    state.engine = create_db_engine(settings.database_url)
    state.session_factory = create_session_factory(state.engine)
    state.redis = create_redis(settings.redis_url)
    state.http = httpx.AsyncClient(timeout=15)
    state.fetcher = SafeFetcher(
        state.http,
        state.redis,
        user_agent=settings.crawler_user_agent,
        delay_seconds=settings.crawl_delay_seconds,
        resolver=None if settings.crawl_allow_private_hosts else ensure_public_host,
    )


@broker.on_event(TaskiqEvents.WORKER_SHUTDOWN)
async def shutdown(state: TaskiqState) -> None:
    await state.http.aclose()
    await state.redis.aclose()
    await state.engine.dispose()


@broker.task(task_name="ingest_url")
async def ingest_url_task(
    url: str, context: Annotated[Context, TaskiqDepends()]
) -> dict[str, Any]:
    state = context.state
    result = await ingest_with_retries(state.session_factory, state.fetcher, url)
    logger.info("%s: %s %s", result.outcome, url, result.detail or "")
    return {
        **asdict(result),
        "outcome": str(result.outcome),
        "page_id": str(result.page_id) if result.page_id else None,
    }
