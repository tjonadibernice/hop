import random
import uuid

import pytest
from sqlalchemy import select

from app.config import settings
from app.models import Interaction
from app.services import hop_queue
from app.services.hop import next_page, refill_queue
from app.services.hop_queue import QUEUE_SIZE, REFILL_BELOW, QueuedPick
from tests.factories import make_page, make_user, react


async def refill(session_factory, redis, user, percent=0):
    async with session_factory() as session:
        return await refill_queue(
            session, redis, user, rng=random.Random(1), recommender_percent=percent
        )


async def hop(session_factory, redis, user):
    async with session_factory() as session:
        return await next_page(session, user, redis=redis, recommender_percent=0)


# --- Filling the queue ------------------------------------------------------------


async def test_refill_queues_distinct_unseen_approved_pages(
    session_factory, redis, topics
):
    user = await make_user(session_factory, [topics[0]])
    good = {(await make_page(session_factory, topics[0])).id for _ in range(12)}
    seen = await make_page(session_factory, topics[0])
    await react(session_factory, user, seen, "like")
    await make_page(session_factory, topics[0], status="rejected")
    await make_page(session_factory, topics[1])  # not in the user's interests

    added = await refill(session_factory, redis, user)

    queued = await hop_queue.peek_all(redis, user)
    assert added == QUEUE_SIZE
    assert len({pick.page_id for pick in queued}) == QUEUE_SIZE
    assert {pick.page_id for pick in queued} <= good
    assert {pick.strategy for pick in queued} == {"random"}
    # Already full: nothing to add
    assert await refill(session_factory, redis, user) == 0


async def test_refill_tops_up_without_repeating_queued_pages(
    session_factory, redis, topics
):
    user = await make_user(session_factory, [topics[0]])
    for _ in range(12):
        await make_page(session_factory, topics[0])
    await refill(session_factory, redis, user)
    for _ in range(7):
        await hop(session_factory, redis, user)

    # 12 pages - 7 seen - 3 still queued = 2 left to add
    assert await refill(session_factory, redis, user) == 2
    queued = await hop_queue.peek_all(redis, user)
    assert len({pick.page_id for pick in queued}) == 5


async def test_recommender_users_get_recommender_picks(session_factory, redis, topics):
    user = await make_user(session_factory, topics)
    for topic in topics:
        for _ in range(5):
            await make_page(session_factory, topic, quality=0.8)

    added = await refill(session_factory, redis, user, percent=100)

    queued = await hop_queue.peek_all(redis, user)
    assert added == QUEUE_SIZE
    assert len({pick.page_id for pick in queued}) == QUEUE_SIZE
    assert {pick.strategy for pick in queued} == {"recommender"}


# --- Serving from the queue -------------------------------------------------------


async def test_hop_serves_the_queue_and_skips_stale_entries(
    session_factory, redis, topics
):
    user = await make_user(session_factory, [topics[0]])
    rejected = await make_page(session_factory, topics[0], status="rejected")
    seen = await make_page(session_factory, topics[0])
    await react(session_factory, user, seen, "like")
    other_topic = await make_page(session_factory, topics[1])
    good = await make_page(session_factory, topics[0])
    await hop_queue.push(
        redis,
        user,
        [
            QueuedPick(rejected.id, "random"),
            QueuedPick(seen.id, "random"),
            QueuedPick(other_topic.id, "random"),
            QueuedPick(good.id, "recommender"),
        ],
    )

    result = await hop(session_factory, redis, user)

    assert result.page.id == good.id
    assert result.source == "queue"
    # The strategy that picked the page is recorded, not the user's current group
    assert result.strategy == "recommender"
    async with session_factory() as session:
        view = await session.scalar(
            select(Interaction).where(
                Interaction.page_id == good.id, Interaction.kind == "view"
            )
        )
    assert view.strategy == "recommender"
    assert await hop_queue.peek_all(redis, user) == []


async def test_hop_picks_live_when_the_queue_is_empty(session_factory, redis, topics):
    user = await make_user(session_factory, [topics[0]])
    page = await make_page(session_factory, topics[0])

    result = await hop(session_factory, redis, user)

    assert (result.page.id, result.source) == (page.id, "live")


async def test_claim_refill_only_once_and_only_when_low(redis):
    user = uuid.uuid4()
    await hop_queue.push(
        redis, user, [QueuedPick(uuid.uuid4(), "random") for _ in range(REFILL_BELOW)]
    )
    assert not await hop_queue.claim_refill(redis, user)  # not low yet

    await hop_queue.pop(redis, user)
    assert await hop_queue.claim_refill(redis, user)
    assert not await hop_queue.claim_refill(redis, user)  # already requested

    await hop_queue.release_refill(redis, user)
    assert await hop_queue.claim_refill(redis, user)


# --- Through the API ----------------------------------------------------------------


async def setup_user(client, session_factory, topics, pages_per_topic=5):
    for topic in topics:
        for _ in range(pages_per_topic):
            await make_page(session_factory, topic)
    response = await client.put(
        "/me/interests", json={"topic_ids": [topic.id for topic in topics]}
    )
    assert response.status_code == 200
    return uuid.UUID((await client.get("/auth/me")).json()["id"])


async def test_first_hop_is_live_and_asks_for_one_refill(
    logged_in_client, session_factory, topics, refiller
):
    user = await setup_user(logged_in_client, session_factory, topics)

    first = await logged_in_client.post("/hop")
    second = await logged_in_client.post("/hop")

    assert first.status_code == 200
    assert first.headers["X-Hop-Source"] == "live"
    assert first.json()["strategy"] in ("random", "recommender")
    # The lock stops a second request while the first refill is pending
    assert second.status_code == 200
    assert refiller.requested == [user]


async def test_hop_uses_the_queue_after_a_refill(
    logged_in_client, session_factory, redis, topics, refiller
):
    user = await setup_user(logged_in_client, session_factory, topics)
    await refill(session_factory, redis, user)
    first_queued = (await hop_queue.peek_all(redis, user))[0]

    response = await logged_in_client.post("/hop")

    assert response.headers["X-Hop-Source"] == "queue"
    assert response.json()["id"] == str(first_queued.page_id)
    assert response.json()["strategy"] == first_queued.strategy
    # 9 pages still queued: no refill needed yet
    assert refiller.requested == []


async def test_changing_interests_clears_the_queue(
    logged_in_client, session_factory, redis, topics
):
    user = await setup_user(logged_in_client, session_factory, topics)
    await refill(session_factory, redis, user)

    await logged_in_client.put(
        "/me/interests", json={"topic_ids": [topic.id for topic in topics]}
    )

    assert await hop_queue.peek_all(redis, user) == []


async def test_the_queue_can_be_turned_off(
    logged_in_client, session_factory, redis, topics, refiller, monkeypatch
):
    monkeypatch.setattr(settings, "hop_queue_enabled", False)
    user = await setup_user(logged_in_client, session_factory, topics)
    await refill(session_factory, redis, user)

    response = await logged_in_client.post("/hop")

    assert response.headers["X-Hop-Source"] == "live"
    assert len(await hop_queue.peek_all(redis, user)) == QUEUE_SIZE
    assert refiller.requested == []


@pytest.mark.parametrize("status", [409, 404])
async def test_no_refill_request_when_there_is_nothing_to_serve(
    logged_in_client, session_factory, topics, refiller, status
):
    if status == 404:
        await setup_user(logged_in_client, session_factory, topics, pages_per_topic=0)

    response = await logged_in_client.post("/hop")

    assert response.status_code == status
    assert refiller.requested == []
