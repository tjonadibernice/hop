"""Link-rot checks: re-fetch approved pages and retire the ones that broke.

A daily scheduled sweep finds approved pages that are due (next_check_at has
passed, or they were never checked) and queues one recheck job per page.

| Result of the check                        | What happens                         |
| ------------------------------------------ | ------------------------------------ |
| Page loads with readable text              | Next check in 30 days                |
| Temporary trouble (timeout, 404, 5xx, ...) | Failure count +1, try again tomorrow |
| 3 failures in a row                        | dead                                 |
| 410 Gone, or robots.txt now blocks us      | dead right away                      |
| Text is now very different (SimHash)       | needs_review (e.g. a parked domain)  |
| Now redirects to another site              | needs_review                         |

Pages that aren't approved are never checked, and Hop only shows approved
pages, so a dead page simply stops appearing.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import undefer

from app.ingestion.discovery import MAX_STORED_LINKS
from app.ingestion.extract import article_links
from app.ingestion.fetch import FetchError, RobotsDisallowedError, SafeFetcher
from app.ingestion.interactive import Unreadable, read_page
from app.ingestion.network import HostNotFoundError, UnsafeUrlError
from app.ingestion.pipeline import HTML_TYPES, MAX_PAGE_BYTES
from app.ingestion.simhash import (
    band_keys,
    from_signed,
    hamming_distance,
    simhash,
    to_signed,
)
from app.ingestion.urls import site_of
from app.models import Page
from app.services.embeds import allows_framing

RECHECK_INTERVAL = timedelta(days=30)
RETRY_AFTER_FAILURE = timedelta(days=1)
MAX_FAILURES = 3
# Bits of SimHash difference that count as "a different page now". Small edits
# stay well under this; unrelated text lands around 32.
CONTENT_CHANGED_DISTANCE = 24
SWEEP_BATCH_SIZE = 200


class CheckOutcome(StrEnum):
    ALIVE = "alive"
    FAILED = "failed"  # counted; the page stays approved for now
    DEAD = "dead"
    CHANGED = "changed"  # sent to needs_review


@dataclass(frozen=True)
class CheckResult:
    page_id: uuid.UUID
    outcome: CheckOutcome
    reason: str | None = None


async def due_page_ids(
    session: AsyncSession, now: datetime, limit: int = SWEEP_BATCH_SIZE
) -> list[uuid.UUID]:
    """Approved pages whose check is due, oldest first (never-checked first of all)."""
    rows = await session.scalars(
        select(Page.id)
        .where(Page.status == "approved")
        .where(or_(Page.next_check_at.is_(None), Page.next_check_at <= now))
        .order_by(Page.next_check_at.asc().nulls_first())
        .limit(limit)
    )
    return list(rows)


def _alive(page: Page, now: datetime) -> CheckOutcome:
    page.check_failures = 0
    page.last_checked_at = now
    page.next_check_at = now + RECHECK_INTERVAL
    return CheckOutcome.ALIVE


def _failed(page: Page, now: datetime, reason: str) -> tuple[CheckOutcome, str]:
    page.check_failures += 1
    page.last_checked_at = now
    if page.check_failures >= MAX_FAILURES:
        page.status = "dead"
        page.status_reason = f"failed {page.check_failures} checks in a row ({reason})"
        page.next_check_at = None
        return CheckOutcome.DEAD, page.status_reason
    page.next_check_at = now + RETRY_AFTER_FAILURE
    return CheckOutcome.FAILED, reason


def _retire(page: Page, now: datetime, status: str, reason: str) -> None:
    page.status = status
    page.status_reason = reason
    page.last_checked_at = now
    page.next_check_at = None
    if status == "needs_review":
        # It changed since anyone approved it: the curator looks again
        page.curated_at = None


async def recheck_page(
    session: AsyncSession,
    fetcher: SafeFetcher,
    page_id: uuid.UUID,
    now: datetime | None = None,
) -> CheckResult | None:
    """Check one approved page and save the result. None if it's not approved."""
    now = now or datetime.now(UTC)
    page = await session.get(Page, page_id, options=[undefer(Page.outlinks)])
    if page is None or page.status != "approved":
        return None

    outcome, reason = await _check(page, fetcher, now)
    await session.commit()
    return CheckResult(page.id, outcome, reason)


async def _check(
    page: Page, fetcher: SafeFetcher, now: datetime
) -> tuple[CheckOutcome, str | None]:
    try:
        fetched = await fetcher.get(page.url, max_bytes=MAX_PAGE_BYTES)
    except RobotsDisallowedError:
        _retire(page, now, "dead", "robots.txt now blocks Hop")
        return CheckOutcome.DEAD, page.status_reason
    except UnsafeUrlError:
        _retire(page, now, "dead", "now points to a private address")
        return CheckOutcome.DEAD, page.status_reason
    except HostNotFoundError:
        return _failed(page, now, "host not found")
    except FetchError as error:
        return _failed(page, now, error.reason)

    if fetched.status_code == 410:
        _retire(page, now, "dead", "gone (HTTP 410)")
        return CheckOutcome.DEAD, page.status_reason
    if fetched.status_code >= 400:
        return _failed(page, now, f"HTTP {fetched.status_code}")

    if site_of(page.url) != site_of(fetched.url):
        _retire(page, now, "needs_review", f"now redirects to {site_of(fetched.url)}")
        return CheckOutcome.CHANGED, page.status_reason

    content_type = fetched.headers.get("content-type", "").split(";")[0].strip().lower()
    if content_type not in HTML_TYPES:
        return _failed(page, now, f"not HTML ({content_type or 'unknown'})")
    try:
        page_read = read_page(fetched.body, fetched.url)
    except Unreadable:
        return _failed(page, now, "no readable content")

    fingerprint = simhash(page_read.text)
    if page.simhash is not None:
        distance = hamming_distance(fingerprint, from_signed(page.simhash))
        if distance > CONTENT_CHANGED_DISTANCE:
            _retire(
                page, now, "needs_review", f"content changed ({distance} of 64 bits)"
            )
            return CheckOutcome.CHANGED, page.status_reason
    else:
        # Hand-picked seed pages were never fingerprinted; do it now
        page.simhash = to_signed(fingerprint)
        page.simhash_bands = band_keys(fingerprint)

    page.embeddable = allows_framing(fetched.headers)
    if page.outlinks is None:
        # Seed pages were never fetched by the pipeline; keep their links now
        page.outlinks = article_links(fetched.body, fetched.url)[:MAX_STORED_LINKS]
    return _alive(page, now), None
