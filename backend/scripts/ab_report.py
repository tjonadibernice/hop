"""Compare the A/B groups: does the recommender beat random picks?

Liked rate = views whose page the viewer currently likes / all views.

Usage, from backend/:  uv run python -m scripts.ab_report
"""

import asyncio

from app.config import settings
from app.db import create_db_engine, create_session_factory
from app.services.experiments import RANDOM, RECOMMENDER, compare, strategy_stats


async def main() -> None:
    engine = create_db_engine(settings.database_url)
    async with create_session_factory(engine)() as session:
        stats = {row.strategy: row for row in await strategy_stats(session)}
    await engine.dispose()

    print(f"Recommender share: {settings.recommender_percent}% of users\n")
    print(
        f"{'Strategy':<12} {'Users':>6} {'Views':>7} {'Likes':>6} {'Dislikes':>9} {'Liked rate':>11}"
    )
    for name in (RANDOM, RECOMMENDER):
        row = stats.get(name)
        if row is None:
            print(f"{name:<12} {'no views yet':>42}")
            continue
        print(
            f"{name:<12} {row.users:>6} {row.views:>7} {row.likes:>6} "
            f"{row.dislikes:>9} {row.liked_rate:>10.1%}"
        )

    if RANDOM in stats and RECOMMENDER in stats:
        result = compare(stats[RANDOM], stats[RECOMMENDER])
        if result is not None:
            verdict = (
                "a real difference (p < 0.05)"
                if result.p_value < 0.05
                else "not distinguishable from chance yet; collect more views"
            )
            print(
                f"\nDifference: {result.difference:+.1%} "
                f"(z = {result.z_score:.2f}, p = {result.p_value:.3f}): {verdict}"
            )


if __name__ == "__main__":
    asyncio.run(main())
