"""Rate limits in Redis, shared by every API process.

Each rule allows `limit` events per `window_seconds`, counted with a sliding
window counter: the current fixed window's count, plus the previous window's
count weighted by how much of it still overlaps the last `window_seconds`.
That smooths out the burst a plain fixed window allows at its boundary
(a full window's worth just before it, another just after), while costing
only two small Redis keys per subject.

Subjects (an IP address, an email) are hashed before they become part of a
key, so Redis never holds a readable email address.
"""

import hashlib
import math
import time
from dataclasses import dataclass

from redis.asyncio import Redis

KEY_PREFIX = "rl"


@dataclass(frozen=True)
class Rule:
    name: str
    limit: int
    window_seconds: int


@dataclass(frozen=True)
class Verdict:
    allowed: bool
    retry_after: int = 0  # seconds until the next event would be allowed


def subject_of(*parts: str) -> str:
    """A short, stable hash of what the limit is about (IP, email, or both)."""
    joined = "\x1f".join(part.strip().lower() for part in parts)
    return hashlib.sha256(joined.encode()).hexdigest()[:32]


def _keys(rule: Rule, subject: str, window: int) -> tuple[str, str]:
    base = f"{KEY_PREFIX}:{rule.name}:{subject}"
    return f"{base}:{window}", f"{base}:{window - 1}"


def _verdict(rule: Rule, current: int, previous: int, elapsed: float) -> Verdict:
    window = rule.window_seconds
    weight = 1 - elapsed / window  # share of the previous window still counted
    if current + previous * weight <= rule.limit:
        return Verdict(True)
    # Waiting lowers the previous window's weight; if the current window alone
    # is at the limit, only the next window helps
    room = rule.limit - current
    if room <= 0 or previous == 0:
        wait = window - elapsed
    else:
        wait = window * (1 - room / previous) - elapsed
    return Verdict(False, max(1, min(window, math.ceil(wait))))


async def hit(
    redis: Redis, rule: Rule, subject: str, now: float | None = None
) -> Verdict:
    """Count one event and say whether it is within the limit.

    Refused events are counted too, so someone who keeps trying stays
    limited instead of getting through every time the window slides.
    """
    now = time.time() if now is None else now
    window = int(now // rule.window_seconds)
    current_key, previous_key = _keys(rule, subject, window)
    async with redis.pipeline(transaction=True) as pipe:
        pipe.incr(current_key)
        pipe.expire(current_key, 2 * rule.window_seconds)
        pipe.get(previous_key)
        current, _, previous = await pipe.execute()
    elapsed = now - window * rule.window_seconds
    # This event counts toward the limit, so allow while the total stays <= limit
    return _verdict(rule, int(current), int(previous or 0), elapsed)


async def peek(
    redis: Redis, rule: Rule, subject: str, now: float | None = None
) -> Verdict:
    """Whether one more event would be allowed, without counting anything.

    Used for limits that count only failures: check first, count with hit()
    after the attempt fails.
    """
    now = time.time() if now is None else now
    window = int(now // rule.window_seconds)
    current_key, previous_key = _keys(rule, subject, window)
    current, previous = await redis.mget(current_key, previous_key)
    elapsed = now - window * rule.window_seconds
    return _verdict(rule, int(current or 0) + 1, int(previous or 0), elapsed)


async def reset(
    redis: Redis, rule: Rule, subject: str, now: float | None = None
) -> None:
    now = time.time() if now is None else now
    window = int(now // rule.window_seconds)
    await redis.delete(*_keys(rule, subject, window))
