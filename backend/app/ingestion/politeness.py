"""Space out requests to the same site, across all workers."""

import asyncio

from redis.asyncio import Redis


async def wait_for_turn(redis: Redis, host: str, delay_seconds: float) -> None:
    """Wait until at least delay_seconds have passed since the last request to host.

    SET NX PX claims the host for delay_seconds; whoever gets the key goes
    first, everyone else sleeps until it expires. Because the key lives in
    Redis, the limit holds even with several workers running.
    """
    key = f"crawl:next:{host}"
    delay_ms = max(int(delay_seconds * 1000), 1)
    while not await redis.set(key, "1", nx=True, px=delay_ms):
        remaining_ms = await redis.pttl(key)
        await asyncio.sleep(max(remaining_ms, 10) / 1000)
