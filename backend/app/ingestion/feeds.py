"""RSS and Atom feeds: a steady supply of new pages from sites you trust.

The feed list lives in feeds.txt next to this file. Once a day the scheduler
queues poll_feeds, which queues one poll_feed job per feed. Each poll fetches
the feed with the same safe fetcher as pages, and queues recent posts Hop
doesn't have yet. Conditional requests (ETag / Last-Modified) mean an
unchanged feed costs the site almost nothing: it answers 304 Not Modified.
"""

import calendar
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import feedparser
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ingestion.fetch import SafeFetcher
from app.ingestion.urls import InvalidUrlError, canonicalize_url
from app.models import Page

FEEDS_FILE = Path(__file__).with_name("feeds.txt")
MAX_FEED_BYTES = 5_000_000
MAX_ENTRIES_PER_FEED = 20
MAX_ENTRY_AGE = timedelta(days=30)
VALIDATORS_TTL_SECONDS = 30 * 24 * 60 * 60


class FeedError(Exception):
    """The feed couldn't be fetched or read; it's tried again next time."""


def load_feeds(path: Path = FEEDS_FILE) -> list[str]:
    lines = (line.strip() for line in path.read_text().splitlines())
    return [line for line in lines if line and not line.startswith("#")]


def parse_feed(body: bytes, now: datetime) -> list[str]:
    """Post URLs from a feed, newest first; posts older than 30 days are skipped.

    Posts without a date are kept: plenty of feeds leave dates out.
    """
    feed = feedparser.parse(body)
    # feedparser doesn't raise on HTML or junk; it just finds no feed version
    if not feed.entries and (feed.bozo or not feed.get("version")):
        raise FeedError("not a readable RSS or Atom feed")

    entries = []
    for entry in feed.entries:
        link = entry.get("link")
        if not link:
            continue
        parsed = entry.get("published_parsed") or entry.get("updated_parsed")
        published = (
            datetime.fromtimestamp(calendar.timegm(parsed), UTC) if parsed else None
        )
        if published is not None and now - published > MAX_ENTRY_AGE:
            continue
        entries.append((published or now, link))

    entries.sort(key=lambda item: item[0], reverse=True)
    return [link for _, link in entries[:MAX_ENTRIES_PER_FEED]]


async def new_post_urls(
    session: AsyncSession,
    fetcher: SafeFetcher,
    redis: Redis,
    feed_url: str,
    now: datetime,
) -> list[str]:
    """Canonical URLs of recent posts in the feed that Hop doesn't have yet."""
    key = f"feed:validators:{feed_url}"
    saved = json.loads(await redis.get(key) or "{}")
    headers = {}
    if saved.get("etag"):
        headers["If-None-Match"] = saved["etag"]
    if saved.get("last_modified"):
        headers["If-Modified-Since"] = saved["last_modified"]

    fetched = await fetcher.get(feed_url, max_bytes=MAX_FEED_BYTES, headers=headers)
    if fetched.status_code == 304:
        return []  # nothing new since last time
    if fetched.status_code >= 400:
        raise FeedError(f"HTTP {fetched.status_code}")

    validators = {
        "etag": fetched.headers.get("etag"),
        "last_modified": fetched.headers.get("last-modified"),
    }
    await redis.set(key, json.dumps(validators), ex=VALIDATORS_TTL_SECONDS)

    urls = []
    for link in parse_feed(fetched.body, now):
        try:
            canonical = canonicalize_url(link)
        except InvalidUrlError:
            continue
        if canonical not in urls:
            urls.append(canonical)
    if not urls:
        return []
    known = set(
        await session.scalars(
            select(Page.canonical_url).where(Page.canonical_url.in_(urls))
        )
    )
    return [url for url in urls if url not in known]
