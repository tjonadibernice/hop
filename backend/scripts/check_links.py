"""Start a link-rot sweep now, instead of waiting for the daily schedule.

The worker must be running. Usage, from backend/:  uv run python -m scripts.check_links
"""

import asyncio

from app.worker import broker, check_links_task


async def main() -> None:
    await broker.startup()
    await check_links_task.kiq()
    await broker.shutdown()
    print("Queued a link check. The worker's log shows pages that failed or died.")


if __name__ == "__main__":
    asyncio.run(main())
