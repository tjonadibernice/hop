"""Check which pages allow being shown in an iframe, and save the result.

Only pages that haven't been checked yet (embeddable is NULL) are fetched,
so it's safe to run again after adding pages.

Usage, from backend/:  uv run python -m scripts.check_embeddable
"""

import asyncio

import httpx
from sqlalchemy import select

from app.config import settings
from app.db import create_db_engine, create_session_factory
from app.models import Page
from app.services.embeds import check_embeddable

MAX_CONCURRENT_REQUESTS = 5


async def main() -> None:
    engine = create_db_engine(settings.database_url)
    session_factory = create_session_factory(engine)
    # Limit parallel requests, to be polite to the sites we fetch
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)

    async with (
        session_factory() as session,
        httpx.AsyncClient(
            headers={"User-Agent": settings.crawler_user_agent},
            follow_redirects=True,
            timeout=10,
        ) as client,
    ):
        pages = list(
            await session.scalars(select(Page).where(Page.embeddable.is_(None)))
        )

        async def check(page: Page) -> None:
            async with semaphore:
                page.embeddable = await check_embeddable(client, page.url)
            print(f"{page.embeddable!s:>5}  {page.url}")

        await asyncio.gather(*(check(page) for page in pages))
        await session.commit()

    await engine.dispose()
    print(f"Checked {len(pages)} pages.")


if __name__ == "__main__":
    asyncio.run(main())
