import random
import uuid
from collections import deque
from collections.abc import Collection
from dataclasses import dataclass
from datetime import UTC, datetime

from redis.asyncio import Redis
from sqlalchemy import exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from app.config import settings
from app.models import Interaction, Page, page_topics, user_interests
from app.models.page import ARTICLE, INTERACTIVE
from app.services import hop_queue
from app.services.experiments import RECOMMENDER, assigned_strategy
from app.services.hop_queue import QueuedPick
from app.services.recommender import recommend_many

QUEUE = "queue"  # served from the user's precomputed queue
LIVE = "live"  # picked while the user waited (queue empty or turned off)


class NoInterestsError(Exception):
    pass


@dataclass(frozen=True)
class Hop:
    page: Page
    strategy: str  # "recommender" or "random"
    source: str  # QUEUE or LIVE


def _strategy(user_id: uuid.UUID, recommender_percent: int | None) -> str:
    percent = (
        settings.recommender_percent
        if recommender_percent is None
        else recommender_percent
    )
    return assigned_strategy(user_id, percent)


async def next_page(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    redis: Redis | None = None,
    rng: random.Random | None = None,
    recommender_percent: int | None = None,
) -> Hop | None:
    """Pick the next page for the user and record the view.

    With `redis`, the page comes from the user's queue when it has a valid
    entry (fast). Otherwise it's picked now: the user's A/B group decides how,
    with the recommender or as a random page from their interests (the
    baseline). Returns None when they've seen every page in their interests.
    """
    hop = None
    if redis is not None:
        # A valid queued page is in the user's interests by definition, so the
        # interests check below is only needed when picking live
        hop = await _from_queue(session, redis, user_id)
    if hop is None:
        has_interests = await session.scalar(
            select(exists().where(user_interests.c.user_id == user_id))
        )
        if not has_interests:
            raise NoInterestsError
        strategy = _strategy(user_id, recommender_percent)
        pages = await _pick(session, user_id, strategy, rng or random.Random(), 1)
        if not pages:
            return None
        hop = Hop(pages[0], strategy, LIVE)

    session.add(
        Interaction(
            user_id=user_id, page_id=hop.page.id, kind="view", strategy=hop.strategy
        )
    )
    await session.commit()
    return hop


async def _from_queue(
    session: AsyncSession, redis: Redis, user_id: uuid.UUID
) -> Hop | None:
    """The first queued page that's still valid. Stale entries are dropped."""
    while (pick := await hop_queue.pop(redis, user_id)) is not None:
        page = await servable_page(session, user_id, pick.page_id)
        if page is not None:
            return Hop(page, pick.strategy, QUEUE)
    return None


async def servable_page(
    session: AsyncSession, user_id: uuid.UUID, page_id: uuid.UUID
) -> Page | None:
    """The page, if it can still be shown: approved, unseen, and in the user's interests.

    A queued page can go stale between the refill and the hop: it was
    rejected or retired, the user changed interests, or another tab showed it.
    """
    interest_topic_ids = select(user_interests.c.topic_id).where(
        user_interests.c.user_id == user_id
    )
    in_interests = exists().where(
        page_topics.c.page_id == Page.id,
        page_topics.c.topic_id.in_(interest_topic_ids),
    )
    seen = exists().where(
        Interaction.user_id == user_id, Interaction.page_id == Page.id
    )
    result = await session.execute(
        select(Page)
        .where(Page.id == page_id)
        .where(Page.status == "approved")
        .where(in_interests)
        .where(~seen)
        # One query for the page and its topics (selectinload would take two)
        .options(joinedload(Page.topics))
    )
    return result.unique().scalar_one_or_none()


async def refill_queue(
    session: AsyncSession,
    redis: Redis,
    user_id: uuid.UUID,
    *,
    rng: random.Random | None = None,
    recommender_percent: int | None = None,
) -> int:
    """Top the user's queue up to QUEUE_SIZE pages. Returns how many were added.

    Runs in the worker (see app/worker.py). Pages already in the queue are
    skipped, so the queue never holds the same page twice.
    """
    queued = await hop_queue.peek_all(redis, user_id)
    missing = hop_queue.QUEUE_SIZE - len(queued)
    if missing <= 0:
        return 0
    strategy = _strategy(user_id, recommender_percent)
    pages = await _pick(
        session,
        user_id,
        strategy,
        rng or random.Random(),
        missing,
        exclude={pick.page_id for pick in queued},
    )
    await hop_queue.push(
        redis, user_id, [QueuedPick(page.id, strategy) for page in pages]
    )
    return len(pages)


def page_kinds(
    count: int, rng: random.Random, interactive_percent: int | None = None
) -> list[str]:
    """The kind each of the next `count` hops should be, drawn independently,
    so about interactive_percent of them are interactive."""
    percent = (
        settings.interactive_percent
        if interactive_percent is None
        else interactive_percent
    )
    return [
        INTERACTIVE if rng.random() * 100 < percent else ARTICLE for _ in range(count)
    ]


async def _pick(
    session: AsyncSession,
    user_id: uuid.UUID,
    strategy: str,
    rng: random.Random,
    count: int,
    exclude: Collection[uuid.UUID] = (),
) -> list[Page]:
    """Up to `count` pages, mixing interactive pages and articles.

    Each slot gets a kind (see page_kinds). Each kind is picked in one batch
    by the user's strategy; when a kind runs short (the user has seen them
    all, or the library has few), any page fills the gap, so the mix never
    stops a user from hopping.
    """
    kinds = page_kinds(count, rng)
    skip = set(exclude)
    pools: dict[str, deque[Page]] = {}
    for kind in (INTERACTIVE, ARTICLE):
        wanted = kinds.count(kind)
        if wanted:
            pages = await _pick_kind(
                session, user_id, strategy, rng, wanted, skip, kind
            )
            skip.update(page.id for page in pages)
            pools[kind] = deque(pages)
    shortfall = count - sum(len(pool) for pool in pools.values())
    spare = deque(
        await _pick_kind(session, user_id, strategy, rng, shortfall, skip, None)
        if shortfall
        else []
    )

    picked = []
    for kind in kinds:
        other = ARTICLE if kind == INTERACTIVE else INTERACTIVE
        for pool in (pools.get(kind), spare, pools.get(other)):
            if pool:
                picked.append(pool.popleft())
                break
    return picked


async def _pick_kind(
    session: AsyncSession,
    user_id: uuid.UUID,
    strategy: str,
    rng: random.Random,
    count: int,
    exclude: Collection[uuid.UUID],
    kind: str | None,
) -> list[Page]:
    if strategy == RECOMMENDER:
        return await recommend_many(
            session, user_id, rng, datetime.now(UTC), count, exclude, kind
        )
    return await random_pages(session, user_id, count, exclude, kind)


async def random_page(session: AsyncSession, user_id: uuid.UUID) -> Page | None:
    """The baseline: a random approved, unseen page from the user's interests."""
    pages = await random_pages(session, user_id, 1)
    return pages[0] if pages else None


async def random_pages(
    session: AsyncSession,
    user_id: uuid.UUID,
    count: int,
    exclude: Collection[uuid.UUID] = (),
    kind: str | None = None,
) -> list[Page]:
    interest_topic_ids = select(user_interests.c.topic_id).where(
        user_interests.c.user_id == user_id
    )
    pages_in_interests = select(page_topics.c.page_id).where(
        page_topics.c.topic_id.in_(interest_topic_ids)
    )
    seen_page_ids = select(Interaction.page_id).where(Interaction.user_id == user_id)

    query = (
        select(Page)
        .where(Page.status == "approved")
        .where(Page.id.in_(pages_in_interests))
        .where(Page.id.not_in(seen_page_ids))
        # Fine for thousands of pages
        .order_by(func.random())
        .limit(count)
        .options(selectinload(Page.topics))
    )
    if exclude:
        query = query.where(Page.id.not_in(list(exclude)))
    if kind is not None:
        query = query.where(Page.kind == kind)
    return list(await session.scalars(query))
