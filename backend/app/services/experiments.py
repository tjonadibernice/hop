"""The A/B test: random picks (the baseline) versus the recommender.

Each user is assigned to one group for good, from a hash of their ID, so the
same person always gets the same strategy and the groups don't mix. Each view
records the strategy that picked it, and the report compares liked rates.
"""

import hashlib
import math
import uuid
from dataclasses import dataclass

from sqlalchemy import and_, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Interaction
from app.services.reactions import latest_reactions

RANDOM = "random"
RECOMMENDER = "recommender"


def assigned_strategy(user_id: uuid.UUID, recommender_percent: int) -> str:
    """Deterministic: a hash of the user ID puts them in bucket 0-99."""
    bucket = int(hashlib.sha256(user_id.bytes).hexdigest()[:8], 16) % 100
    return RECOMMENDER if bucket < recommender_percent else RANDOM


@dataclass(frozen=True)
class StrategyStats:
    strategy: str
    users: int
    views: int
    likes: int
    dislikes: int

    @property
    def liked_rate(self) -> float:
        return self.likes / self.views if self.views else 0.0


@dataclass(frozen=True)
class Comparison:
    difference: float  # recommender liked rate minus random liked rate
    z_score: float
    p_value: float  # chance of a difference this big if there were none


async def strategy_stats(session: AsyncSession) -> list[StrategyStats]:
    """Views per strategy, and how many of those pages the viewer now likes."""
    latest = latest_reactions()
    rows = await session.execute(
        select(
            Interaction.strategy,
            func.count(func.distinct(Interaction.user_id)),
            func.count(),
            func.count(case((latest.c.kind == "like", 1))),
            func.count(case((latest.c.kind == "dislike", 1))),
        )
        .outerjoin(
            latest,
            and_(
                latest.c.user_id == Interaction.user_id,
                latest.c.page_id == Interaction.page_id,
            ),
        )
        .where(Interaction.kind == "view", Interaction.strategy.is_not(None))
        .group_by(Interaction.strategy)
        .order_by(Interaction.strategy)
    )
    return [StrategyStats(*row) for row in rows]


def compare(baseline: StrategyStats, candidate: StrategyStats) -> Comparison | None:
    """Two-proportion z-test on liked rates. None if either group has no views."""
    n1, n2 = baseline.views, candidate.views
    if not n1 or not n2:
        return None
    p1, p2 = baseline.liked_rate, candidate.liked_rate
    pooled = (baseline.likes + candidate.likes) / (n1 + n2)
    spread = math.sqrt(pooled * (1 - pooled) * (1 / n1 + 1 / n2))
    if spread == 0:
        return Comparison(p2 - p1, 0.0, 1.0)
    z = (p2 - p1) / spread
    p_value = math.erfc(abs(z) / math.sqrt(2))  # two-sided
    return Comparison(p2 - p1, z, p_value)
