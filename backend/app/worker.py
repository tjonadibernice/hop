"""Background worker for the ingestion pipeline (taskiq + Redis Streams).

Tasks:
- ingest_url: fetch a URL and store it as a pending page, then queue
  enrich_page, which decides whether the page is approved, rejected, or
  needs review.
- check_links (daily, 03:00 UTC): queue recheck_page for every approved page
  that's due, which retires pages that broke (see ingestion/linkrot.py).

Run the worker with:     uv run taskiq worker app.worker:broker
Run the scheduler with:  uv run taskiq scheduler app.worker:scheduler
Queue URLs with:         uv run python -m scripts.enqueue_urls scripts/sources.txt
"""

import logging
import uuid
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Annotated, Any

import httpx
from taskiq import Context, TaskiqDepends, TaskiqEvents, TaskiqScheduler, TaskiqState
from taskiq.schedule_sources import LabelScheduleSource
from taskiq_redis import RedisAsyncResultBackend, RedisStreamBroker

from app.ai.embeddings import VoyageEmbedder
from app.ai.llm import LLMRouter, providers_from_settings
from app.cache import create_redis
from app.config import settings
from app.db import create_db_engine, create_session_factory
from app.ingestion.enrich import EnrichServices, enrich_with_retries
from app.ingestion.fetch import SafeFetcher
from app.ingestion.linkrot import due_page_ids, recheck_page
from app.ingestion.network import ensure_public_host
from app.ingestion.pipeline import Outcome, ingest_with_retries
from app.ingestion.safety import SafetyChecker, load_blocklist
from app.models import EMBEDDING_DIMENSIONS

logger = logging.getLogger(__name__)

# httpx logs every request URL at INFO level. That's noisy for a crawler, and a
# URL can carry secrets, so only its warnings are shown.
logging.getLogger("httpx").setLevel(logging.WARNING)

RESULT_TTL_SECONDS = 7 * 24 * 60 * 60

# Redis Streams keep a message until a worker acknowledges it, so a job isn't
# lost if a worker crashes halfway through
broker = RedisStreamBroker(
    url=settings.redis_url, queue_name="hop:ingest"
).with_result_backend(
    RedisAsyncResultBackend(settings.redis_url, result_ex_time=RESULT_TTL_SECONDS)
)

# Reads the schedule="..." labels on the tasks below. Run exactly one
# scheduler process: two would queue every scheduled job twice.
scheduler = TaskiqScheduler(broker, sources=[LabelScheduleSource(broker)])


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

    # Model calls can be slow; give them their own client and timeout
    state.ai_http = httpx.AsyncClient(timeout=60)
    providers = providers_from_settings(settings)
    if not providers:
        logger.warning(
            "No LLM provider configured: set GEMINI_API_KEY, OPENAI_API_KEY, "
            "or OLLAMA_BASE_URL. Enrichment jobs will fail until you do."
        )
    state.enrich = EnrichServices(
        llm=LLMRouter(state.ai_http, state.redis, providers),
        safety=SafetyChecker(
            state.ai_http,
            api_key=settings.safe_browsing_api_key,
            blocklist=load_blocklist(),
        ),
        embedder=(
            VoyageEmbedder(
                state.ai_http,
                settings.voyage_api_key,
                settings.voyage_model,
                EMBEDDING_DIMENSIONS,
            )
            if settings.voyage_api_key
            else None
        ),
    )


@broker.on_event(TaskiqEvents.WORKER_SHUTDOWN)
async def shutdown(state: TaskiqState) -> None:
    await state.http.aclose()
    await state.ai_http.aclose()
    await state.redis.aclose()
    await state.engine.dispose()


@broker.task(task_name="ingest_url")
async def ingest_url_task(
    url: str, context: Annotated[Context, TaskiqDepends()]
) -> dict[str, Any]:
    state = context.state
    result = await ingest_with_retries(state.session_factory, state.fetcher, url)
    logger.info("%s: %s %s", result.outcome, url, result.detail or "")
    if result.outcome == Outcome.ADDED and result.page_id is not None:
        await enrich_page_task.kiq(str(result.page_id))
    return {
        **asdict(result),
        "outcome": str(result.outcome),
        "page_id": str(result.page_id) if result.page_id else None,
    }


@broker.task(task_name="enrich_page")
async def enrich_page_task(
    page_id: str, context: Annotated[Context, TaskiqDepends()]
) -> dict[str, Any] | None:
    state = context.state
    result = await enrich_with_retries(
        state.session_factory, state.enrich, uuid.UUID(page_id)
    )
    if result is None:
        logger.info("skipped %s: not pending anymore", page_id)
        return None
    logger.info(
        "%s: %s (%s) via %s", result.status, page_id, result.reason, result.provider
    )
    return {**asdict(result), "page_id": page_id}


@broker.task(
    task_name="check_links",
    schedule=[{"cron": "0 3 * * *", "schedule_id": "daily-link-check"}],
)
async def check_links_task(context: Annotated[Context, TaskiqDepends()]) -> dict:
    """Queue a recheck for every approved page that's due (up to a batch)."""
    async with context.state.session_factory() as session:
        page_ids = await due_page_ids(session, datetime.now(UTC))
    for page_id in page_ids:
        await recheck_page_task.kiq(str(page_id))
    logger.info("link check: queued %d pages", len(page_ids))
    return {"queued": len(page_ids)}


@broker.task(task_name="recheck_page")
async def recheck_page_task(
    page_id: str, context: Annotated[Context, TaskiqDepends()]
) -> dict[str, Any] | None:
    state = context.state
    async with state.session_factory() as session:
        result = await recheck_page(session, state.fetcher, uuid.UUID(page_id))
    if result is None:
        return None
    if result.outcome != "alive":
        logger.info("link check %s: %s (%s)", result.outcome, page_id, result.reason)
    return {**asdict(result), "page_id": page_id}
