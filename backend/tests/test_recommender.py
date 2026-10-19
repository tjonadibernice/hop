import json
import random
from collections import Counter
from datetime import timedelta

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.orm import undefer

from app.ai.embeddings import VoyageEmbedder
from app.ingestion.backfill import backfill_embeddings
from app.models import EMBEDDING_DIMENSIONS, Interaction, Page
from app.services.hop import next_page
from app.services.recommender import (
    COLD_START_REACTIONS,
    TopicCounts,
    candidate_pages,
    choose,
    recommend,
    taste_vector,
    topic_order,
)
from tests.factories import NOW, axis, make_page, make_user, mix, react

# --- Thompson sampling over topics ------------------------------------------


def first_choices(counts, draws=2000, seed=1) -> Counter:
    rng = random.Random(seed)
    return Counter(topic_order(counts, rng)[0] for _ in range(draws))


def test_a_loved_topic_usually_comes_first():
    firsts = first_choices({1: TopicCounts(20, 0), 2: TopicCounts(0, 20)})
    assert firsts[1] > 0.99 * 2000


def test_unknown_topics_split_evenly():
    firsts = first_choices({1: TopicCounts(), 2: TopicCounts()})
    assert 0.45 < firsts[1] / 2000 < 0.55


def test_an_untried_topic_still_gets_explored():
    # Topic 1 is liked (3 of 4); topic 2 has no data, so its wide Beta(1, 1)
    # sometimes draws higher. That's exploration.
    firsts = first_choices({1: TopicCounts(3, 1), 2: TopicCounts()})
    assert 0.1 * 2000 < firsts[2] < 0.5 * 2000


def test_closer_candidates_are_chosen_more_often():
    rng = random.Random(3)
    picks = Counter(choose(["near", "mid", "far"], rng) for _ in range(3000))
    assert picks["near"] > picks["mid"] > picks["far"]


# --- Taste vector ----------------------------------------------------------------


async def test_taste_points_toward_likes_and_away_from_dislikes(
    session_factory, topics
):
    user = await make_user(session_factory, topics)
    await react(
        session_factory,
        user,
        await make_page(session_factory, topics[0], embedding=axis(0)),
        "like",
    )
    await react(
        session_factory,
        user,
        await make_page(session_factory, topics[0], embedding=axis(1)),
        "dislike",
    )

    async with session_factory() as session:
        taste = await taste_vector(session, user, NOW)

    assert taste[0] > 0.85  # mostly the liked direction
    assert taste[1] < 0  # pushed away from the disliked one
    assert abs(sum(x * x for x in taste) - 1) < 1e-9  # unit length


async def test_older_likes_count_less(session_factory, topics):
    user = await make_user(session_factory, topics)
    old = await make_page(session_factory, topics[0], embedding=axis(0))
    new = await make_page(session_factory, topics[0], embedding=axis(1))
    await react(session_factory, user, old, "like", when=NOW - timedelta(days=60))
    await react(session_factory, user, new, "like", when=NOW)

    async with session_factory() as session:
        taste = await taste_vector(session, user, NOW)

    # 60 days = two half-lives: the old like weighs a quarter as much
    assert taste[1] / taste[0] == pytest.approx(4)


async def test_no_likes_means_no_taste(session_factory, topics):
    user = await make_user(session_factory, topics)
    await react(
        session_factory,
        user,
        await make_page(session_factory, topics[0], embedding=axis(1)),
        "dislike",
    )

    async with session_factory() as session:
        assert await taste_vector(session, user, NOW) is None


# --- Picking pages -------------------------------------------------------------------


async def test_candidates_are_nearest_to_taste(session_factory, topics):
    user = await make_user(session_factory, topics)
    far = await make_page(session_factory, topics[0], embedding=axis(5))
    near = await make_page(
        session_factory, topics[0], embedding=mix((0, 0.9), (5, 0.1))
    )
    middle = await make_page(
        session_factory, topics[0], embedding=mix((0, 0.5), (5, 0.5))
    )

    async with session_factory() as session:
        pages = await candidate_pages(session, user, topics[0].id, axis(0))

    assert [p.id for p in pages] == [near.id, middle.id, far.id]


async def test_cold_start_ranks_by_quality(session_factory, topics):
    user = await make_user(session_factory, [topics[0]])
    await make_page(session_factory, topics[0], quality=0.3)
    best = await make_page(session_factory, topics[0], quality=0.95)
    await make_page(session_factory, topics[0], quality=0.6)

    async with session_factory() as session:
        pages = await candidate_pages(session, user, topics[0].id, None)

    assert pages[0].id == best.id


async def test_recommend_uses_taste_after_enough_reactions(session_factory, topics):
    user = await make_user(session_factory, [topics[0]])
    for _ in range(COLD_START_REACTIONS):
        liked = await make_page(session_factory, topics[0], embedding=axis(0))
        await react(session_factory, user, liked, "like")
    match = await make_page(session_factory, topics[0], embedding=axis(0), quality=0.4)
    for _ in range(3):
        await make_page(session_factory, topics[0], embedding=axis(7), quality=0.99)

    picks = Counter()
    for seed in range(30):
        async with session_factory() as session:
            page = await recommend(session, user, random.Random(seed), NOW)
            picks[page.id == match.id] += 1

    # The matching page wins most often despite its lower quality score
    assert picks[True] > picks[False]


async def test_recommend_skips_seen_and_unapproved_pages(session_factory, topics):
    user = await make_user(session_factory, [topics[0]])
    seen = await make_page(session_factory, topics[0])
    await react(session_factory, user, seen, "like")
    await make_page(session_factory, topics[0], status="pending")
    fresh = await make_page(session_factory, topics[0])

    async with session_factory() as session:
        page = await recommend(session, user, random.Random(1), NOW)
    assert page.id == fresh.id


async def test_recommend_returns_none_when_everything_is_seen(session_factory, topics):
    user = await make_user(session_factory, [topics[0]])
    await react(
        session_factory, user, await make_page(session_factory, topics[0]), "like"
    )

    async with session_factory() as session:
        assert await recommend(session, user, random.Random(1), NOW) is None


async def test_pages_without_embeddings_are_still_reachable(session_factory, topics):
    user = await make_user(session_factory, [topics[0]])
    for _ in range(COLD_START_REACTIONS):
        await react(
            session_factory,
            user,
            await make_page(session_factory, topics[0], embedding=axis(0)),
            "like",
        )
    unembedded = await make_page(session_factory, topics[0])

    async with session_factory() as session:
        page = await recommend(session, user, random.Random(1), NOW)
    assert page.id == unembedded.id


# --- Hops record their strategy ---------------------------------------------------------


@pytest.mark.parametrize(("percent", "strategy"), [(0, "random"), (100, "recommender")])
async def test_views_record_the_strategy(session_factory, topics, percent, strategy):
    user = await make_user(session_factory, [topics[0]])
    await make_page(session_factory, topics[0])

    async with session_factory() as session:
        page = await next_page(session, user, recommender_percent=percent)
    async with session_factory() as session:
        view = await session.scalar(
            select(Interaction).where(
                Interaction.page_id == page.id, Interaction.kind == "view"
            )
        )
    assert view.strategy == strategy


# --- Embedding backfill -------------------------------------------------------------------


async def test_backfill_embeds_approved_pages_without_embeddings(
    session_factory, topics
):
    requests = []

    def voyage(request):
        requests.append(request)
        count = len(json.loads(request.content)["input"])
        return httpx.Response(
            200,
            json={"data": [{"index": i, "embedding": axis(i)} for i in range(count)]},
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(voyage))
    embedder = VoyageEmbedder(client, "v", "voyage-4-lite", EMBEDDING_DIMENSIONS)
    seeds = [await make_page(session_factory, topics[0]) for _ in range(3)]
    already = await make_page(session_factory, topics[0], embedding=axis(9))
    pending = await make_page(session_factory, topics[0], status="pending")

    done = await backfill_embeddings(session_factory, embedder, batch_size=2)

    assert done == 3
    assert len(requests) == 2  # batches of 2, then 1
    async with session_factory() as session:
        pages = {
            p.id: p
            for p in await session.scalars(
                select(Page).options(undefer(Page.embedding))
            )
        }
    assert all(pages[p.id].embedding is not None for p in seeds)
    assert pages[already.id].embedding[9] == 1.0  # untouched
    assert pages[pending.id].embedding is None
