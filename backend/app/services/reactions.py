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


def latest_reactions(user_id: uuid.UUID | None = None):
    """Each (user, page)'s newest like or dislike, as a subquery.

    Columns: user_id, page_id, kind, created_at. Pass user_id to limit it to
    one user.
    """
    query = select(
        Interaction.user_id,
        Interaction.page_id,
        Interaction.kind,
        Interaction.created_at,
    ).where(Interaction.kind.in_(("like", "dislike")))
    if user_id is not None:
        query = query.where(Interaction.user_id == user_id)
    # DISTINCT ON keeps the first row per (user, page) in this order:
    # the newest reaction (id breaks ties within the same timestamp)
    return (
        query.ext(distinct_on(Interaction.user_id, Interaction.page_id))
        .order_by(
            Interaction.user_id,
            Interaction.page_id,
            Interaction.created_at.desc(),
            Interaction.id.desc(),
        )
        .subquery()
    )


async def liked_pages(session: AsyncSession, user_id: uuid.UUID) -> Sequence[Page]:
    """Pages whose most recent reaction from this user is a like, newest first."""
    latest = latest_reactions(user_id)
    result = await session.scalars(
        select(Page)
        .join(latest, latest.c.page_id == Page.id)
        .where(latest.c.kind == "like")
        # Pages an admin removed or purged disappear from everyone's likes
        .where(Page.status != "rejected")
        .order_by(latest.c.created_at.desc())
        .options(selectinload(Page.topics))
    )
    return result.all()
