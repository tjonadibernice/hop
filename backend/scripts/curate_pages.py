"""Queue every needs_review page the curator agent hasn't reviewed yet.

New review pages are queued automatically, and an hourly job catches any it
missed. Use this to start right away, for example on pages that were waiting
for review before the curator existed. The worker must be running.

Usage, from backend/:  uv run python -m scripts.curate_pages
"""

import asyncio

from app.config import settings
from app.curator.service import uncurated_page_ids
from app.db import create_db_engine, create_session_factory
from app.worker import broker, curate_page_task


async def main() -> None:
    if not settings.curator_enabled:
        raise SystemExit("CURATOR_ENABLED is false; nothing queued.")
    engine = create_db_engine(settings.database_url)
    async with create_session_factory(engine)() as session:
        page_ids = await uncurated_page_ids(session)
    await engine.dispose()

    await broker.startup()
    for page_id in page_ids:
        await curate_page_task.kiq(str(page_id))
    await broker.shutdown()
    print(f"Queued {len(page_ids)} pages for the curator. Watch the worker's log.")


if __name__ == "__main__":
    asyncio.run(main())
