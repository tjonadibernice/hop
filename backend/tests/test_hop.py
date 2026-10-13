import pytest
from sqlalchemy import func, select

from app.models import Interaction, Page, Topic


@pytest.fixture
async def topics_by_slug(session_factory) -> dict[str, Topic]:
    async with session_factory() as session:
        return {topic.slug: topic for topic in await session.scalars(select(Topic))}


async def add_pages(session_factory, topic: Topic, count: int) -> None:
    async with session_factory() as session:
        for number in range(count):
            session.add(
                Page(
                    url=f"https://example.com/{topic.slug}/{number}",
                    title=f"{topic.name} {number}",
                    topics=[await session.merge(topic)],
                )
            )
        await session.commit()


async def choose_interests(client, topics: list[Topic]) -> None:
    response = await client.put(
        "/me/interests", json={"topic_ids": [topic.id for topic in topics]}
    )
    assert response.status_code == 200


async def test_hop_requires_login(client):
    assert (await client.post("/hop")).status_code == 401


async def test_hop_requires_interests(logged_in_client):
    response = await logged_in_client.post("/hop")

    assert response.status_code == 409
    assert response.json() == {"detail": "Choose at least 3 interests first."}


async def test_hop_returns_page_from_interests(
    logged_in_client, session_factory, topics_by_slug
):
    chosen = [
        topics_by_slug[s]
        for s in ("cybersecurity", "data-databases", "habits-routines")
    ]
    await add_pages(session_factory, chosen[0], 1)
    await add_pages(session_factory, topics_by_slug["language-learning"], 5)
    await choose_interests(logged_in_client, chosen)

    response = await logged_in_client.post("/hop")

    assert response.status_code == 200
    page = response.json()
    assert page["url"] == "https://example.com/cybersecurity/0"
    assert page["topics"][0]["slug"] == "cybersecurity"


async def test_hop_never_repeats_and_ends_when_all_seen(
    logged_in_client, session_factory, topics_by_slug
):
    chosen = [
        topics_by_slug[s]
        for s in ("cybersecurity", "data-databases", "habits-routines")
    ]
    await add_pages(session_factory, chosen[0], 2)
    await add_pages(session_factory, chosen[1], 1)
    await choose_interests(logged_in_client, chosen)

    urls = [(await logged_in_client.post("/hop")).json()["url"] for _ in range(3)]
    last = await logged_in_client.post("/hop")

    assert len(set(urls)) == 3
    assert last.status_code == 404


async def test_hop_records_a_view(logged_in_client, session_factory, topics_by_slug):
    chosen = [
        topics_by_slug[s]
        for s in ("cybersecurity", "data-databases", "habits-routines")
    ]
    await add_pages(session_factory, chosen[0], 1)
    await choose_interests(logged_in_client, chosen)

    await logged_in_client.post("/hop")

    async with session_factory() as session:
        views = await session.scalar(
            select(func.count())
            .select_from(Interaction)
            .where(Interaction.kind == "view")
        )
    assert views == 1
