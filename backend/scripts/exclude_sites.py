"""Take pages from the sites in excluded_sites.txt out of Hop.

Run after adding a site to app/ingestion/excluded_sites.txt (Wikipedia is
there already). Safe to run again: it only changes pages still in use.

Usage, from backend/:  uv run python -m scripts.exclude_sites
"""

import asyncio

from app.config import settings
from app.db import create_db_engine, create_session_factory
from app.ingestion.exclusions import retire_excluded_pages
from app.ingestion.safety import EXCLUDED_SITES


async def main() -> None:
    engine = create_db_engine(settings.database_url)
    async with create_session_factory(engine)() as session:
        retired = await retire_excluded_pages(session)
    await engine.dispose()
    sites = ", ".join(sorted(EXCLUDED_SITES))
    print(f"Took {retired} pages out of Hop (excluded sites: {sites}).")


if __name__ == "__main__":
    asyncio.run(main())
