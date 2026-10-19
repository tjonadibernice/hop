import random
import uuid
from datetime import UTC, datetime

from sqlalchemy import exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.models import Interaction, Page, page_topics, user_interests
from app.services.experiments import RECOMMENDER, assigned_strategy
from app.services.recommender import recommend


class NoInterestsError(Exception):
    pass


async def next_page(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    rng: random.Random | None = None,
    recommender_percent: int | None = None,
) -> Page | None:
    """Pick the next page for the user and record the view.

    The user's A/B group decides how: the recommender, or a random page from
    their interests (the baseline). Returns None when they've seen every page
    in their interests.
    """
    has_interests = await session.scalar(
        select(exists().where(user_interests.c.user_id == user_id))
    )
    if not has_interests:
        raise NoInterestsError

    percent = (
        settings.recommender_percent
        if recommender_percent is None
        else recommender_percent
    )
    strategy = assigned_strategy(user_id, percent)
    if strategy == RECOMMENDER:
        page = await recommend(
            session, user_id, rng or random.Random(), datetime.now(UTC)
        )
    else:
        page = await random_page(session, user_id)
    if page is None:
        return None

    session.add(
        Interaction(user_id=user_id, page_id=page.id, kind="view", strategy=strategy)
    )
    await session.commit()
    return page


async def random_page(session: AsyncSession, user_id: uuid.UUID) -> Page | None:
    """The baseline: a random approved, unseen page from the user's interests."""
    interest_topic_ids = select(user_interests.c.topic_id).where(
        user_interests.c.user_id == user_id
    )
    pages_in_interests = select(page_topics.c.page_id).where(
        page_topics.c.topic_id.in_(interest_topic_ids)
    )
    seen_page_ids = select(Interaction.page_id).where(Interaction.user_id == user_id)

    return await session.scalar(
        select(Page)
        .where(Page.status == "approved")
        .where(Page.id.in_(pages_in_interests))
        .where(Page.id.not_in(seen_page_ids))
        # Fine for thousands of pages
        .order_by(func.random())
        .limit(1)
        .options(selectinload(Page.topics))
    )
