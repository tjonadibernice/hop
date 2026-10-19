import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from app.ingestion.feeds import (
    MAX_ENTRIES_PER_FEED,
    FeedError,
    load_feeds,
    new_post_urls,
    parse_feed,
)
from app.models import Page
from tests.web import FakeWeb

NOW = datetime(2026, 10, 19, tzinfo=UTC)
FEED = "https://blog.test/atom.xml"


def iso(days_ago: int) -> str:
    return (NOW - timedelta(days=days_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


def atom(entries: list[tuple[str, int | None]]) -> bytes:
    items = "".join(
        f'<entry><title>{url}</title><link href="{url}"/>'
        + (f"<updated>{iso(age)}</updated>" if age is not None else "")
        + "</entry>"
        for url, age in entries
    )
    return (
        '<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom">'
        f"<title>Blog</title>{items}</feed>"
    ).encode()


def rss(entries: list[tuple[str, int]]) -> bytes:
    items = "".join(
        f"<item><title>{url}</title><link>{url}</link>"
        f"<pubDate>{(NOW - timedelta(days=age)).strftime('%a, %d %b %Y %H:%M:%S +0000')}</pubDate></item>"
        for url, age in entries
    )
    return f'<?xml version="1.0"?><rss version="2.0"><channel><title>B</title>{items}</channel></rss>'.encode()


# --- Reading feeds ------------------------------------------------------------


def test_atom_posts_newest_first_and_old_ones_skipped():
    body = atom(
        [
            ("https://blog.test/old", 90),
            ("https://blog.test/b", 5),
            ("https://blog.test/a", 1),
        ]
    )

    assert parse_feed(body, NOW) == ["https://blog.test/a", "https://blog.test/b"]


def test_rss_works_too():
    body = rss([("https://blog.test/x", 2)])

    assert parse_feed(body, NOW) == ["https://blog.test/x"]


def test_posts_without_dates_are_kept():
    assert parse_feed(atom([("https://blog.test/undated", None)]), NOW) == [
        "https://blog.test/undated"
    ]


def test_long_feeds_are_capped():
    body = atom([(f"https://blog.test/{n}", 1) for n in range(50)])

    assert len(parse_feed(body, NOW)) == MAX_ENTRIES_PER_FEED


def test_not_a_feed_raises():
    with pytest.raises(FeedError):
        parse_feed(b"<html><body>Just a page</body></html>", NOW)


def test_shipped_feed_list_loads():
    assert isinstance(load_feeds(), list)


# --- Polling a feed -------------------------------------------------------------


@pytest.fixture
def web() -> FakeWeb:
    return FakeWeb()


async def poll(session_factory, web, redis):
    async with session_factory() as session:
        return await new_post_urls(session, web.fetcher(redis), redis, FEED, NOW)


async def test_new_posts_are_returned_and_known_ones_skipped(
    session_factory, web, redis
):
    async with session_factory() as session:
        url = "https://blog.test/known"
        session.add(Page(url=url, canonical_url=url, title="T"))
        await session.commit()
    web.add(
        FEED,
        httpx.Response(
            200,
            content=atom(
                [
                    ("https://blog.test/known", 1),
                    ("https://blog.test/new?utm_source=rss", 2),
                ]
            ),
        ),
    )

    assert await poll(session_factory, web, redis) == ["https://blog.test/new"]


async def test_unchanged_feed_is_cheap(session_factory, web, redis):
    requests = []

    def handler(request):
        requests.append(request)
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        if request.headers.get("if-none-match") == '"v1"':
            return httpx.Response(304)
        return httpx.Response(
            200, content=atom([("https://blog.test/a", 1)]), headers={"etag": '"v1"'}
        )

    web.handler = handler

    first = await poll(session_factory, web, redis)
    second = await poll(session_factory, web, redis)

    assert first == ["https://blog.test/a"]
    assert second == []  # 304 Not Modified
    assert json.loads(await redis.get(f"feed:validators:{FEED}"))["etag"] == '"v1"'


async def test_broken_feed_raises(session_factory, web, redis):
    web.add(FEED, httpx.Response(404))

    with pytest.raises(FeedError, match="404"):
        await poll(session_factory, web, redis)
