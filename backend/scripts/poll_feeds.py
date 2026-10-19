"""Check the feeds in app/ingestion/feeds.txt now, instead of waiting for 02:00 UTC.

The worker must be running. Usage, from backend/:  uv run python -m scripts.poll_feeds
"""

import asyncio

from app.worker import broker, poll_feeds_task


async def main() -> None:
    await broker.startup()
    await poll_feeds_task.kiq()
    await broker.shutdown()
    print("Queued a feed check. The worker's log shows new posts per feed.")


if __name__ == "__main__":
    asyncio.run(main())
