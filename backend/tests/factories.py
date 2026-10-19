"""Small helpers that create users, pages, and reactions for recommender tests."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import insert

from app.models import (
    EMBEDDING_DIMENSIONS,
    Interaction,
    Page,
    User,
    page_topics,
    user_interests,
)

NOW = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)


def axis(i: int, scale: float = 1.0) -> list[float]:
    """A vector pointing along one axis: easy to reason about distances."""
    vector = [0.0] * EMBEDDING_DIMENSIONS
    vector[i] = scale
    return vector


def mix(*parts: tuple[int, float]) -> list[float]:
    vector = [0.0] * EMBEDDING_DIMENSIONS
    for i, value in parts:
        vector[i] = value
    return vector


async def make_user(session_factory, topic_list) -> uuid.UUID:
    async with session_factory() as session:
        user = User(email=f"{uuid.uuid4().hex}@example.com", password_hash="x")
        session.add(user)
        await session.flush()
        await session.execute(
            insert(user_interests),
            [{"user_id": user.id, "topic_id": topic.id} for topic in topic_list],
        )
        await session.commit()
        return user.id


async def make_page(
    session_factory, topic, *, embedding=None, quality=None, status="approved"
) -> Page:
    url = f"https://pages.test/{uuid.uuid4().hex}"
    async with session_factory() as session:
        page = Page(
            url=url,
            canonical_url=url,
            title=url,
            status=status,
            embedding=embedding,
            quality_score=quality,
        )
        session.add(page)
        await session.flush()
        await session.execute(
            insert(page_topics), [{"page_id": page.id, "topic_id": topic.id}]
        )
        await session.commit()
        return page


async def react(session_factory, user_id, page, kind, when=NOW):
    async with session_factory() as session:
        session.add(
            Interaction(user_id=user_id, page_id=page.id, kind="view", created_at=when)
        )
        session.add(
            Interaction(user_id=user_id, page_id=page.id, kind=kind, created_at=when)
        )
        await session.commit()
