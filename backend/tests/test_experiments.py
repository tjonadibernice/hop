import uuid

import pytest

from app.models import Interaction
from app.services.experiments import (
    RANDOM,
    RECOMMENDER,
    StrategyStats,
    assigned_strategy,
    compare,
    strategy_stats,
)
from tests.factories import make_page, make_user


def test_assignment_is_stable_and_split_evenly():
    users = [uuid.uuid4() for _ in range(4000)]
    groups = [assigned_strategy(user, 50) for user in users]

    assert groups == [assigned_strategy(user, 50) for user in users]  # stable
    assert 0.45 < groups.count(RECOMMENDER) / len(users) < 0.55


def test_zero_and_hundred_percent():
    user = uuid.uuid4()
    assert assigned_strategy(user, 0) == RANDOM
    assert assigned_strategy(user, 100) == RECOMMENDER


def test_z_test_matches_a_worked_example():
    # 10% vs 20% liked over 100 views each: the classic borderline case
    baseline = StrategyStats(RANDOM, users=10, views=100, likes=10, dislikes=5)
    candidate = StrategyStats(RECOMMENDER, users=10, views=100, likes=20, dislikes=5)

    result = compare(baseline, candidate)

    assert result.difference == pytest.approx(0.10)
    assert result.z_score == pytest.approx(1.98, abs=0.01)
    assert result.p_value == pytest.approx(0.048, abs=0.002)


def test_no_views_means_no_comparison():
    empty = StrategyStats(RANDOM, 0, 0, 0, 0)
    some = StrategyStats(RECOMMENDER, 1, 5, 1, 0)
    assert compare(empty, some) is None


async def test_stats_count_views_and_current_reactions(session_factory, topics):
    user = await make_user(session_factory, topics)
    pages = [await make_page(session_factory, topics[0]) for _ in range(3)]
    async with session_factory() as session:
        for page in pages:
            session.add(
                Interaction(
                    user_id=user, page_id=page.id, kind="view", strategy=RECOMMENDER
                )
            )
        # Liked, then changed to dislike: only the latest counts
        session.add(Interaction(user_id=user, page_id=pages[0].id, kind="like"))
        session.add(Interaction(user_id=user, page_id=pages[0].id, kind="dislike"))
        session.add(Interaction(user_id=user, page_id=pages[1].id, kind="like"))
        await session.commit()

    async with session_factory() as session:
        [row] = await strategy_stats(session)

    assert (row.strategy, row.users, row.views, row.likes, row.dislikes) == (
        RECOMMENDER,
        1,
        3,
        1,
        1,
    )
    assert row.liked_rate == pytest.approx(1 / 3)
