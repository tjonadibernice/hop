import uuid
from collections.abc import Sequence

from sqlalchemy import exists, select
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import Interaction, Page


class PageNotViewedError(Exception):
    pass


async def react(
    session: AsyncSession, user_id: uuid.UUID, page_id: uuid.UUID, reaction: str
) -> None:
    """Record a like or dislike. Users can only react to pages Hop showed them."""
    viewed = await session.scalar(
        select(
            exists().where(
                Interaction.user_id == user_id,
                Interaction.page_id == page_id,
                Interaction.kind == "view",
            )
        )
    )
    if not viewed:
        raise PageNotViewedError

    # Append, never update: the latest reaction is the current one,
    # and the full history stays available for the recommender
    session.add(Interaction(user_id=user_id, page_id=page_id, kind=reaction))
    await session.commit()


async def liked_pages(session: AsyncSession, user_id: uuid.UUID) -> Sequence[Page]:
    """Pages whose most recent reaction from this user is a like, newest first."""
    latest_reactions = (
        select(Interaction.page_id, Interaction.kind, Interaction.created_at)
        .where(
            Interaction.user_id == user_id,
            Interaction.kind.in_(("like", "dislike")),
        )
        # DISTINCT ON keeps the first row per page_id in this order:
        # the newest reaction (id breaks ties within the same timestamp)
        .ext(distinct_on(Interaction.page_id))
        .order_by(
            Interaction.page_id,
            Interaction.created_at.desc(),
            Interaction.id.desc(),
        )
        .subquery()
    )

    result = await session.scalars(
        select(Page)
        .join(latest_reactions, latest_reactions.c.page_id == Page.id)
        .where(latest_reactions.c.kind == "like")
        .order_by(latest_reactions.c.created_at.desc())
        .options(selectinload(Page.topics))
    )
    return result.all()
