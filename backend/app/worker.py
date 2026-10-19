"""Background worker for the ingestion pipeline (taskiq + Redis Streams).

Tasks:
- ingest_url: fetch a URL and store it as a pending page, then queue
  enrich_page, which decides whether the page is approved, rejected, or
  needs review.
- check_links (daily, 03:00 UTC): queue recheck_page for every approved page
  that's due, which retires pages that broke (see ingestion/linkrot.py).
- enrich_pending (hourly, at :15): re-queue pending pages whose enrichment
  gave up earlier (for example, every LLM provider was rate limited).
- poll_feeds (daily, 02:00 UTC): queue poll_feed for every feed in
  ingestion/feeds.txt, which queues new posts for ingestion.
- After a page is approved (or passes a link check for the first time), its
  article links are queued for ingestion too (see ingestion/discovery.py).

Run the worker with:     uv run taskiq worker app.worker:broker
Run the scheduler with:  uv run taskiq scheduler app.worker:scheduler
Queue URLs with:         uv run python -m scripts.enqueue_urls scripts/sources.txt
"""

import logging
import uuid
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
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
from app.ingestion.discovery import links_to_queue
from app.ingestion.enrich import EnrichServices, enrich_with_retries, pending_page_ids
from app.ingestion.feeds import FeedError, load_feeds, new_post_urls
from app.ingestion.fetch import FetchError, RobotsDisallowedError, SafeFetcher
from app.ingestion.linkrot import due_page_ids, recheck_page
from app.ingestion.network import HostNotFoundError, UnsafeUrlError, ensure_public_host
from app.ingestion.pipeline import Outcome, ingest_with_retries
from app.ingestion.safety import SafetyChecker, load_blocklist
from app.models import EMBEDDING_DIMENSIONS

logger = logging.getLogger(__name__)

# httpx logs every request URL at INFO level. That's noisy for a crawler, and a
# URL can carry secrets, so only its warnings are shown.
logging.getLogger("httpx").setLevel(logging.WARNING)

RESULT_TTL_SECONDS = 7 * 24 * 60 * 60
ENRICH_LOCK_SECONDS = 30 * 60
SWEEP_SKIPS_NEWER_THAN = timedelta(minutes=10)
SWEEP_BATCH_SIZE = 100

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
    state.blocklist = load_blocklist()
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
            blocklist=state.blocklist,
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


async def share_links(state: TaskiqState, page_id: uuid.UUID) -> int:
    """Queue an approved page's article links for ingestion (once per page)."""
    async with state.session_factory() as session:
        links, depth = await links_to_queue(session, page_id, state.blocklist)
    for link in links:
        await ingest_url_task.kiq(link, source="link", depth=depth)
    if links:
        logger.info("discovery: %s shared %d links", page_id, len(links))
    return len(links)


@broker.task(task_name="ingest_url")
async def ingest_url_task(
    url: str,
    context: Annotated[Context, TaskiqDepends()],
    source: str = "manual",
    depth: int = 0,
) -> dict[str, Any]:
    state = context.state
    result = await ingest_with_retries(
        state.session_factory, state.fetcher, url, source=source, depth=depth
    )
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
    # The hourly sweep can queue a page that's already queued; the lock makes
    # sure only one job enriches it (and pays for the LLM call)
    lock = f"enrich:lock:{page_id}"
    if not await state.redis.set(lock, "1", nx=True, ex=ENRICH_LOCK_SECONDS):
        logger.info("skipped %s: already being enriched", page_id)
        return None
    try:
        result = await enrich_with_retries(
            state.session_factory, state.enrich, uuid.UUID(page_id)
        )
    finally:
        await state.redis.delete(lock)
    if result is None:
        logger.info("skipped %s: not pending anymore", page_id)
        return None
    logger.info(
        "%s: %s (%s) via %s", result.status, page_id, result.reason, result.provider
    )
    if result.status == "approved":
        await share_links(state, result.page_id)
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
    if result.outcome == "alive":
        # Seed pages share their links after their first successful check
        await share_links(state, result.page_id)
    else:
        logger.info("link check %s: %s (%s)", result.outcome, page_id, result.reason)
    return {**asdict(result), "page_id": page_id}


@broker.task(
    task_name="enrich_pending",
    schedule=[{"cron": "15 * * * *", "schedule_id": "hourly-enrich-sweep"}],
)
async def enrich_pending_task(context: Annotated[Context, TaskiqDepends()]) -> dict:
    """Re-queue pending pages whose enrichment gave up earlier."""
    older_than = datetime.now(UTC) - SWEEP_SKIPS_NEWER_THAN
    async with context.state.session_factory() as session:
        page_ids = await pending_page_ids(session, older_than, SWEEP_BATCH_SIZE)
    for page_id in page_ids:
        await enrich_page_task.kiq(str(page_id))
    if page_ids:
        logger.info("enrich sweep: queued %d pending pages", len(page_ids))
    return {"queued": len(page_ids)}


@broker.task(
    task_name="poll_feeds",
    schedule=[{"cron": "0 2 * * *", "schedule_id": "daily-feed-poll"}],
)
async def poll_feeds_task(context: Annotated[Context, TaskiqDepends()]) -> dict:
    """Queue one poll_feed job per feed in feeds.txt."""
    feeds = load_feeds()
    for feed_url in feeds:
        await poll_feed_task.kiq(feed_url)
    logger.info("feeds: queued %d feeds", len(feeds))
    return {"queued": len(feeds)}


@broker.task(task_name="poll_feed")
async def poll_feed_task(
    feed_url: str, context: Annotated[Context, TaskiqDepends()]
) -> dict[str, Any]:
    """Queue the feed's recent posts that Hop doesn't have yet."""
    state = context.state
    try:
        async with state.session_factory() as session:
            urls = await new_post_urls(
                session, state.fetcher, state.redis, feed_url, datetime.now(UTC)
            )
    except (
        FeedError,
        FetchError,
        RobotsDisallowedError,
        UnsafeUrlError,
        HostNotFoundError,
    ) as error:
        # A broken feed shouldn't stop the others; it's tried again tomorrow
        logger.warning("feed failed: %s (%s)", feed_url, error)
        return {
            "feed": feed_url,
            "queued": 0,
            "error": str(error) or type(error).__name__,
        }
    for url in urls:
        await ingest_url_task.kiq(url, source="feed")
    logger.info("feed %s: %d new posts", feed_url, len(urls))
    return {"feed": feed_url, "queued": len(urls)}
