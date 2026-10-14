"""Load the starter set of pages from seed_pages.json into the database.

These pages are hand-picked, so they're stored as approved right away.

Safe to run more than once: pages that already exist (same URL) are skipped.

Usage, from backend/:  uv run python -m scripts.seed_pages
"""

import asyncio
import json
from pathlib import Path

from sqlalchemy import select

from app.config import settings
from app.db import create_db_engine, create_session_factory
from app.ingestion.urls import canonicalize_url
from app.models import Page, Topic

SEED_FILE = Path(__file__).with_name("seed_pages.json")


async def seed() -> None:
    entries = json.loads(SEED_FILE.read_text())
    engine = create_db_engine(settings.database_url)
    session_factory = create_session_factory(engine)

    async with session_factory() as session:
        topics_by_slug = {
            topic.slug: topic for topic in await session.scalars(select(Topic))
        }
        existing_urls = set(await session.scalars(select(Page.url)))

        added = 0
        for entry in entries:
            if entry["url"] in existing_urls:
                continue
            unknown = [s for s in entry["topics"] if s not in topics_by_slug]
            if unknown:
                raise SystemExit(f"Unknown topic {unknown} for {entry['url']}")

            session.add(
                Page(
                    url=entry["url"],
                    canonical_url=canonicalize_url(entry["url"]),
                    title=entry["title"],
                    summary=entry["summary"],
                    topics=[topics_by_slug[slug] for slug in entry["topics"]],
                    # Hand-picked, so they skip review
                    status="approved",
                )
            )
            added += 1

        await session.commit()

    await engine.dispose()
    print(f"Added {added} pages ({len(entries) - added} already existed).")


if __name__ == "__main__":
    asyncio.run(seed())
