"""Queue every pending page that hasn't been enriched yet.

New pages are queued automatically after they're fetched, and an hourly job
re-queues leftovers. Use this to do it right away, for example after adding
API keys.

Usage, from backend/:  uv run python -m scripts.enqueue_enrichment
"""

import asyncio
from datetime import UTC, datetime

from app.config import settings
from app.db import create_db_engine, create_session_factory
from app.ingestion.enrich import pending_page_ids
from app.worker import broker, enrich_page_task


async def main() -> None:
    engine = create_db_engine(settings.database_url)
    async with create_session_factory(engine)() as session:
        page_ids = await pending_page_ids(session, older_than=datetime.now(UTC))
    await engine.dispose()

    await broker.startup()
    for page_id in page_ids:
        await enrich_page_task.kiq(str(page_id))
    await broker.shutdown()
    print(f"Queued {len(page_ids)} pending pages for enrichment.")


if __name__ == "__main__":
    asyncio.run(main())
