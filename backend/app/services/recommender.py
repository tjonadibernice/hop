"""The recommender: pick a page the user will probably like, but not always the obvious one.

Two decisions per hop:

1. Which topic? (exploration) Thompson sampling. For each of the user's
   interests, keep a Beta(likes + 1, dislikes + 1) distribution of "how much
   do they like this topic", draw one random sample from each, and try topics
   from the highest draw down. A loved topic usually wins, but a topic with
   little data has a wide distribution, so it sometimes draws high and gets a
   turn. That's how Hop keeps learning and stays surprising.

2. Which page in that topic? (exploitation) The user's taste vector is a
   weighted average of the embeddings of pages they reacted to: likes add,
   dislikes subtract half as much, and older reactions fade (30-day half-life).
   pgvector returns the approved, unseen pages closest to it; one of the top
   10 is chosen, with closer pages more likely.

Cold start: with fewer than 10 reactions, there's no reliable taste yet, so
pages in the chosen topic are ranked by their quality score instead.
"""

import math
import random
import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import Interaction, Page, page_topics, user_interests
from app.services.reactions import latest_reactions

COLD_START_REACTIONS = 10
TASTE_HISTORY = 200  # most recent reactions used for the taste vector
HALF_LIFE_DAYS = 30
DISLIKE_WEIGHT = 0.5
CANDIDATES = 10


@dataclass(frozen=True)
class TopicCounts:
    likes: int = 0
    dislikes: int = 0


async def topic_counts(
    session: AsyncSession, user_id: uuid.UUID, topic_ids: list[int]
) -> dict[int, TopicCounts]:
    """The user's current likes and dislikes per topic (a page counts for each of its topics)."""
    latest = latest_reactions(user_id)
    rows = await session.execute(
        select(
            page_topics.c.topic_id,
            func.count(case((latest.c.kind == "like", 1))),
            func.count(case((latest.c.kind == "dislike", 1))),
        )
        .join(latest, latest.c.page_id == page_topics.c.page_id)
        .where(page_topics.c.topic_id.in_(topic_ids))
        .group_by(page_topics.c.topic_id)
    )
    counts = {topic_id: TopicCounts() for topic_id in topic_ids}
    for topic_id, likes, dislikes in rows:
        counts[topic_id] = TopicCounts(likes, dislikes)
    return counts


def topic_order(counts: dict[int, TopicCounts], rng: random.Random) -> list[int]:
    """Thompson sampling: topics ordered by one random draw from each Beta."""
    draws = {
        topic_id: rng.betavariate(c.likes + 1, c.dislikes + 1)
        for topic_id, c in counts.items()
    }
    return sorted(draws, key=draws.__getitem__, reverse=True)


async def reaction_count(session: AsyncSession, user_id: uuid.UUID) -> int:
    latest = latest_reactions(user_id)
    return await session.scalar(select(func.count()).select_from(latest)) or 0


async def taste_vector(
    session: AsyncSession, user_id: uuid.UUID, now: datetime
) -> list[float] | None:
    """Unit-length taste vector, or None if the user has no liked page with an embedding."""
    latest = latest_reactions(user_id)
    rows = await session.execute(
        select(latest.c.kind, latest.c.created_at, Page.embedding)
        .join(Page, Page.id == latest.c.page_id)
        .where(Page.embedding.is_not(None))
        .order_by(latest.c.created_at.desc())
        .limit(TASTE_HISTORY)
    )
    total: list[float] | None = None
    liked_any = False
    for kind, created_at, embedding in rows:
        age_days = max((now - created_at).total_seconds() / 86_400, 0.0)
        weight = 0.5 ** (age_days / HALF_LIFE_DAYS)
        if kind == "like":
            liked_any = True
        else:
            weight *= -DISLIKE_WEIGHT
        if total is None:
            total = [0.0] * len(embedding)
        for i, value in enumerate(embedding):
            total[i] += weight * value

    if not liked_any or total is None:
        return None
    length = math.sqrt(sum(value * value for value in total))
    if length == 0:
        return None
    return [value / length for value in total]


async def candidate_pages(
    session: AsyncSession,
    user_id: uuid.UUID,
    topic_id: int,
    taste: list[float] | None,
    limit: int = CANDIDATES,
) -> list[Page]:
    """Approved, unseen pages in the topic: closest to the taste, or best quality first."""
    seen = select(Interaction.page_id).where(Interaction.user_id == user_id)
    in_topic = select(page_topics.c.page_id).where(page_topics.c.topic_id == topic_id)
    query = (
        select(Page)
        .where(Page.status == "approved")
        .where(Page.id.in_(in_topic))
        .where(Page.id.not_in(seen))
        .options(selectinload(Page.topics))
        .limit(limit)
    )
    if taste is not None:
        # <=> in SQL: cosine distance, served by the HNSW index
        query = query.where(Page.embedding.is_not(None)).order_by(
            Page.embedding.cosine_distance(taste)
        )
    else:
        query = query.order_by(Page.quality_score.desc().nulls_last(), func.random())
    return list(await session.scalars(query))


def choose(candidates: list[Page], rng: random.Random) -> Page:
    """Closer pages are likelier: weight 1, 1/2, 1/3, ... by rank."""
    weights = [1 / (rank + 1) for rank in range(len(candidates))]
    return rng.choices(candidates, weights=weights, k=1)[0]


async def recommend(
    session: AsyncSession,
    user_id: uuid.UUID,
    rng: random.Random,
    now: datetime,
) -> Page | None:
    """The next page for the user, or None if they've seen everything in their interests."""
    topic_ids = list(
        await session.scalars(
            select(user_interests.c.topic_id).where(user_interests.c.user_id == user_id)
        )
    )
    counts = await topic_counts(session, user_id, topic_ids)
    taste = None
    if await reaction_count(session, user_id) >= COLD_START_REACTIONS:
        taste = await taste_vector(session, user_id, now)

    for topic_id in topic_order(counts, rng):
        candidates = await candidate_pages(session, user_id, topic_id, taste)
        if not candidates and taste is not None:
            # Pages without embeddings yet (e.g. not backfilled) still count
            candidates = await candidate_pages(session, user_id, topic_id, None)
        if candidates:
            return choose(candidates, rng)
    return None
