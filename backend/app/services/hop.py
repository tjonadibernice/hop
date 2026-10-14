import uuid

from sqlalchemy import exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import Interaction, Page, page_topics, user_interests


class NoInterestsError(Exception):
    pass


async def next_page(session: AsyncSession, user_id: uuid.UUID) -> Page | None:
    """Pick a random unseen page from the user's interests and record the view.

    Returns None when the user has seen every page in their interests.
    """
    has_interests = await session.scalar(
        select(exists().where(user_interests.c.user_id == user_id))
    )
    if not has_interests:
        raise NoInterestsError

    interest_topic_ids = select(user_interests.c.topic_id).where(
        user_interests.c.user_id == user_id
    )
    pages_in_interests = select(page_topics.c.page_id).where(
        page_topics.c.topic_id.in_(interest_topic_ids)
    )
    seen_page_ids = select(Interaction.page_id).where(Interaction.user_id == user_id)

    page = await session.scalar(
        select(Page)
        .where(Page.status == "approved")
        .where(Page.id.in_(pages_in_interests))
        .where(Page.id.not_in(seen_page_ids))
        # Fine for thousands of pages; the recommender will replace this
        .order_by(func.random())
        .limit(1)
        .options(selectinload(Page.topics))
    )
    if page is None:
        return None

    session.add(Interaction(user_id=user_id, page_id=page.id, kind="view"))
    await session.commit()
    return page
