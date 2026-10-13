import uuid
from collections.abc import Sequence

from sqlalchemy import delete, func, insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Topic, user_interests


class UnknownTopicError(Exception):
    pass


async def list_topics(session: AsyncSession) -> Sequence[Topic]:
    result = await session.scalars(select(Topic).order_by(Topic.id))
    return result.all()


async def get_interests(session: AsyncSession, user_id: uuid.UUID) -> Sequence[Topic]:
    result = await session.scalars(
        select(Topic)
        .join(user_interests, user_interests.c.topic_id == Topic.id)
        .where(user_interests.c.user_id == user_id)
        .order_by(Topic.id)
    )
    return result.all()


async def set_interests(
    session: AsyncSession, user_id: uuid.UUID, topic_ids: list[int]
) -> Sequence[Topic]:
    """Replace the user's interests with exactly these topics."""
    existing = await session.scalar(
        select(func.count()).select_from(Topic).where(Topic.id.in_(topic_ids))
    )
    if existing != len(topic_ids):
        raise UnknownTopicError

    # Delete and insert in one transaction: other requests never see
    # a half-updated list
    await session.execute(
        delete(user_interests).where(user_interests.c.user_id == user_id)
    )
    await session.execute(
        insert(user_interests),
        [{"user_id": user_id, "topic_id": topic_id} for topic_id in topic_ids],
    )
    await session.commit()
    return await get_interests(session, user_id)
