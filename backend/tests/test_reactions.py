import uuid

import pytest
from sqlalchemy import select

from app.models import Page, Topic

INTEREST_SLUGS = ("cybersecurity", "data-databases", "habits-routines")


@pytest.fixture
async def hopper(logged_in_client, session_factory):
    """A logged-in client with interests and 3 unseen pages to hop through."""
    async with session_factory() as session:
        topics = list(
            await session.scalars(select(Topic).where(Topic.slug.in_(INTEREST_SLUGS)))
        )
        for number in range(3):
            session.add(
                Page(
                    url=f"https://example.com/page/{number}",
                    title=f"Page {number}",
                    topics=[topics[0]],
                )
            )
        await session.commit()

    response = await logged_in_client.put(
        "/me/interests", json={"topic_ids": [topic.id for topic in topics]}
    )
    assert response.status_code == 200
    return logged_in_client


async def hop(client) -> str:
    response = await client.post("/hop")
    assert response.status_code == 200
    return response.json()["id"]


async def react(client, page_id: str, reaction: str):
    return await client.put(f"/pages/{page_id}/reaction", json={"reaction": reaction})


async def liked_ids(client) -> list[str]:
    response = await client.get("/me/likes")
    assert response.status_code == 200
    return [page["id"] for page in response.json()]


async def test_reactions_require_login(client):
    response = await react(client, str(uuid.uuid4()), "like")

    assert response.status_code == 401
    assert (await client.get("/me/likes")).status_code == 401


async def test_like_a_page_from_a_hop(hopper):
    page_id = await hop(hopper)

    response = await react(hopper, page_id, "like")

    assert response.status_code == 200
    assert response.json() == {"page_id": page_id, "reaction": "like"}
    assert await liked_ids(hopper) == [page_id]


async def test_cannot_react_to_a_page_never_shown(hopper, session_factory):
    async with session_factory() as session:
        unseen = await session.scalar(select(Page.id).limit(1))

    shown_never = await react(hopper, str(unseen), "like")
    nonexistent = await react(hopper, str(uuid.uuid4()), "like")

    assert shown_never.status_code == nonexistent.status_code == 404
    assert shown_never.json() == nonexistent.json() == {"detail": "Page not found."}


async def test_latest_reaction_wins(hopper):
    page_id = await hop(hopper)
    await react(hopper, page_id, "like")

    await react(hopper, page_id, "dislike")

    assert await liked_ids(hopper) == []


async def test_likes_are_newest_first(hopper):
    first = await hop(hopper)
    second = await hop(hopper)
    await react(hopper, first, "like")
    await react(hopper, second, "like")

    assert await liked_ids(hopper) == [second, first]


async def test_disliked_pages_are_not_in_likes(hopper):
    liked = await hop(hopper)
    disliked = await hop(hopper)
    await react(hopper, liked, "like")
    await react(hopper, disliked, "dislike")

    assert await liked_ids(hopper) == [liked]


async def test_invalid_reaction_is_rejected(hopper):
    page_id = await hop(hopper)

    response = await react(hopper, page_id, "love")

    assert response.status_code == 422
