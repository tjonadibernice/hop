"""Space out requests (to one website, or to one LLM provider), across all workers."""

import asyncio

from redis.asyncio import Redis


async def wait_for_slot(redis: Redis, key: str, interval_seconds: float) -> None:
    """Wait until at least interval_seconds have passed since the last holder of key.

    SET NX PX claims the key for interval_seconds; whoever gets it goes first,
    everyone else sleeps until it expires. Because the key lives in Redis, the
    spacing holds even with several workers running.
    """
    interval_ms = max(int(interval_seconds * 1000), 1)
    while not await redis.set(key, "1", nx=True, px=interval_ms):
        remaining_ms = await redis.pttl(key)
        await asyncio.sleep(max(remaining_ms, 10) / 1000)


async def wait_for_turn(redis: Redis, host: str, delay_seconds: float) -> None:
    """Wait until at least delay_seconds have passed since the last request to host."""
    await wait_for_slot(redis, f"crawl:next:{host}", delay_seconds)
