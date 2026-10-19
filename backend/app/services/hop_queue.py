"""Each user's queue of ready-to-serve pages, stored in Redis.

Picking a page with the recommender takes several database queries and some
math (the taste vector). Doing that while the user waits is too slow under
load, so the worker picks pages ahead of time and keeps up to QUEUE_SIZE of
them in a Redis list per user:

    hop:queue:{user_id}  ->  ["<page id>:<strategy>", ...]

POST /hop pops the first entry (one fast Redis call). When fewer than
REFILL_BELOW entries are left, it asks the worker to top the queue up. A lock
makes sure only one refill per user is queued at a time.

The queue is only a cache of suggestions. Entries can go stale (the page was
rejected, the user changed interests), so services/hop.py re-checks every
entry before serving it, and falls back to picking live if the queue is empty.
"""

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from redis.asyncio import Redis

QUEUE_SIZE = 10
REFILL_BELOW = 4
QUEUE_TTL_SECONDS = 24 * 60 * 60  # inactive users don't keep a queue forever
REFILL_LOCK_SECONDS = 60  # safety net: the worker releases it when done

# How the API asks for a refill: in production, a function that queues the
# worker job; in tests, a fake that records the call
Refiller = Callable[[uuid.UUID], Awaitable[None]]


@dataclass(frozen=True)
class QueuedPick:
    page_id: uuid.UUID
    strategy: str  # "recommender" or "random"


def queue_key(user_id: uuid.UUID) -> str:
    return f"hop:queue:{user_id}"


def refill_lock_key(user_id: uuid.UUID) -> str:
    return f"hop:refill-lock:{user_id}"


def _encode(pick: QueuedPick) -> str:
    return f"{pick.page_id}:{pick.strategy}"


def _decode(entry: str) -> QueuedPick:
    page_id, strategy = entry.split(":", 1)
    return QueuedPick(uuid.UUID(page_id), strategy)


async def pop(redis: Redis, user_id: uuid.UUID) -> QueuedPick | None:
    entry = await redis.lpop(queue_key(user_id))
    return None if entry is None else _decode(entry)


async def peek_all(redis: Redis, user_id: uuid.UUID) -> list[QueuedPick]:
    return [_decode(entry) for entry in await redis.lrange(queue_key(user_id), 0, -1)]


async def push(redis: Redis, user_id: uuid.UUID, picks: list[QueuedPick]) -> None:
    if not picks:
        return
    key = queue_key(user_id)
    async with redis.pipeline(transaction=True) as pipe:
        pipe.rpush(key, *(_encode(pick) for pick in picks))
        pipe.expire(key, QUEUE_TTL_SECONDS)
        await pipe.execute()


async def clear(redis: Redis, user_id: uuid.UUID) -> None:
    """Drop the queue, for example when the user's interests change."""
    await redis.delete(queue_key(user_id))


async def claim_refill(redis: Redis, user_id: uuid.UUID) -> bool:
    """True if the queue is running low and nobody has asked for a refill yet.

    The caller that gets True must ask the worker for a refill; the worker
    releases the lock when it's done.
    """
    if await redis.llen(queue_key(user_id)) >= REFILL_BELOW:
        return False
    return bool(
        await redis.set(refill_lock_key(user_id), "1", nx=True, ex=REFILL_LOCK_SECONDS)
    )


async def release_refill(redis: Redis, user_id: uuid.UUID) -> None:
    await redis.delete(refill_lock_key(user_id))
