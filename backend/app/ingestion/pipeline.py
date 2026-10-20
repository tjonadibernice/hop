"""Turn a URL into a pending page: fetch, extract, dedupe, store."""

import asyncio
import logging
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.ingestion.discovery import MAX_STORED_LINKS
from app.ingestion.extract import article_links
from app.ingestion.fetch import FetchError, RobotsDisallowedError, SafeFetcher
from app.ingestion.interactive import (
    INTERACTIVE,
    MIN_ARTICLE_WORDS,
    Unreadable,
    read_page,
)
from app.ingestion.network import HostNotFoundError, UnsafeUrlError
from app.ingestion.safety import is_excluded
from app.ingestion.simhash import (
    NEAR_DUPLICATE_DISTANCE,
    band_keys,
    from_signed,
    hamming_distance,
    simhash,
    to_signed,
)
from app.ingestion.urls import InvalidUrlError, canonicalize_url, site_of
from app.models import Page
from app.services.embeds import allows_framing

logger = logging.getLogger(__name__)

MAX_PAGE_BYTES = 2_000_000
MIN_WORDS = MIN_ARTICLE_WORDS  # for articles; interactive pages need less
HTML_TYPES = ("text/html", "application/xhtml+xml")
RETRY_DELAYS_SECONDS = (10, 60)  # wait before the 2nd and 3rd attempts


class Outcome(StrEnum):
    ADDED = "added"
    DUPLICATE = "duplicate"
    NEAR_DUPLICATE = "near_duplicate"
    INVALID_URL = "invalid_url"
    EXCLUDED_SITE = "excluded_site"
    UNSAFE_URL = "unsafe_url"
    BLOCKED_BY_ROBOTS = "blocked_by_robots"
    FETCH_FAILED = "fetch_failed"
    NOT_HTML = "not_html"
    NO_CONTENT = "no_content"
    TOO_SHORT = "too_short"


@dataclass(frozen=True)
class IngestResult:
    outcome: Outcome
    url: str
    page_id: uuid.UUID | None = None
    detail: str | None = None


def _same_host(a: str, b: str) -> bool:
    return urlsplit(a).hostname == urlsplit(b).hostname


def _choose_canonical(fetched_url: str, declared: str | None) -> str:
    """Trust the page's own canonical link only if it stays on the same site.

    Otherwise any page could claim to be another site's page and block it as
    a duplicate.
    """
    if declared:
        try:
            candidate = canonicalize_url(declared)
        except InvalidUrlError:
            candidate = None
        if candidate and _same_host(candidate, fetched_url):
            return candidate
    return canonicalize_url(fetched_url)


async def _canonical_exists(session: AsyncSession, canonical: str) -> bool:
    found = await session.scalar(
        select(Page.id).where(Page.canonical_url == canonical).limit(1)
    )
    return found is not None


async def _find_near_duplicate(
    session: AsyncSession, fingerprint: int, keys: list[int]
) -> uuid.UUID | None:
    # The GIN index finds pages sharing at least one band; compare those exactly
    rows = await session.execute(
        select(Page.id, Page.simhash).where(Page.simhash_bands.overlap(keys))
    )
    for page_id, other in rows:
        if other is not None:
            distance = hamming_distance(fingerprint, from_signed(other))
            if distance <= NEAR_DUPLICATE_DISTANCE:
                return page_id
    return None


async def ingest_url(
    session: AsyncSession,
    fetcher: SafeFetcher,
    url: str,
    *,
    source: str = "manual",
    depth: int = 0,
) -> IngestResult:
    """Fetch one URL and store it as a pending page.

    source says where the URL came from (manual, feed, or link) and depth how
    many links away it is from a page a person or a feed chose.

    Raises FetchError(retryable=True) for problems that may go away
    (timeouts, server errors); every other problem becomes an outcome.
    """
    try:
        canonical = canonicalize_url(url)
    except InvalidUrlError as error:
        return IngestResult(Outcome.INVALID_URL, url, detail=str(error))
    if is_excluded(canonical):
        return IngestResult(Outcome.EXCLUDED_SITE, url)
    if await _canonical_exists(session, canonical):
        return IngestResult(Outcome.DUPLICATE, url)

    try:
        fetched = await fetcher.get(canonical, max_bytes=MAX_PAGE_BYTES)
    except UnsafeUrlError:
        return IngestResult(Outcome.UNSAFE_URL, url)
    except HostNotFoundError:
        return IngestResult(Outcome.FETCH_FAILED, url, detail="host_not_found")
    except RobotsDisallowedError:
        return IngestResult(Outcome.BLOCKED_BY_ROBOTS, url)
    except FetchError as error:
        if error.retryable:
            raise
        return IngestResult(Outcome.FETCH_FAILED, url, detail=error.reason)

    status = fetched.status_code
    if status == 429 or status >= 500:
        raise FetchError(f"http_{status}", retryable=True)
    if status >= 400:
        return IngestResult(Outcome.FETCH_FAILED, url, detail=f"http_{status}")

    content_type = fetched.headers.get("content-type", "").split(";")[0].strip().lower()
    if content_type not in HTML_TYPES:
        return IngestResult(Outcome.NOT_HTML, url, detail=content_type or None)

    if is_excluded(fetched.url):  # redirected to an excluded site
        return IngestResult(Outcome.EXCLUDED_SITE, url)
    try:
        page_read = read_page(fetched.body, fetched.url)
    except Unreadable as error:
        return IngestResult(Outcome(error.reason), url, detail=error.detail)

    # Redirects or a canonical link can reveal a page we already have
    final_canonical = _choose_canonical(fetched.url, page_read.canonical_url)
    if final_canonical != canonical and await _canonical_exists(
        session, final_canonical
    ):
        return IngestResult(Outcome.DUPLICATE, url)

    fingerprint = simhash(page_read.text)
    keys = band_keys(fingerprint)
    # An interactive page's short profile isn't enough to call two pages
    # copies of each other (tools on one site share a lot of wording)
    if page_read.kind != INTERACTIVE:
        original = await _find_near_duplicate(session, fingerprint, keys)
        if original is not None:
            return IngestResult(
                Outcome.NEAR_DUPLICATE, url, detail=f"same as {original}"
            )

    page = Page(
        url=fetched.url,
        canonical_url=final_canonical,
        site=site_of(final_canonical),
        source=source,
        depth=depth,
        outlinks=article_links(fetched.body, fetched.url)[:MAX_STORED_LINKS],
        title=(page_read.title or final_canonical)[:300],
        kind=page_read.kind,
        content=page_read.text,
        word_count=page_read.word_count,
        simhash=to_signed(fingerprint),
        simhash_bands=keys,
        embeddable=allows_framing(fetched.headers),
        status="pending",
        last_checked_at=datetime.now(UTC),
    )
    session.add(page)
    try:
        await session.commit()
    except IntegrityError:
        # Another worker stored the same page a moment ago
        await session.rollback()
        return IngestResult(Outcome.DUPLICATE, url)
    return IngestResult(Outcome.ADDED, url, page_id=page.id)


async def ingest_with_retries(
    session_factory: async_sessionmaker[AsyncSession],
    fetcher: SafeFetcher,
    url: str,
    delays: Sequence[float] = RETRY_DELAYS_SECONDS,
    *,
    source: str = "manual",
    depth: int = 0,
) -> IngestResult:
    """ingest_url, retried with growing waits when the failure may be temporary."""
    for attempt in range(len(delays) + 1):
        try:
            async with session_factory() as session:
                return await ingest_url(
                    session, fetcher, url, source=source, depth=depth
                )
        except FetchError as error:
            if attempt == len(delays):
                return IngestResult(Outcome.FETCH_FAILED, url, detail=error.reason)
            logger.info("Retrying %s in %ss (%s)", url, delays[attempt], error.reason)
            await asyncio.sleep(delays[attempt])
    raise AssertionError("unreachable")
