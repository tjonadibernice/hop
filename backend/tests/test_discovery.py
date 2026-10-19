from datetime import UTC, datetime

import pytest

from app.ingestion.discovery import (
    MAX_LINKS_PER_PAGE,
    MAX_PAGES_PER_SITE,
    choose_links,
    links_to_queue,
)
from app.ingestion.extract import article_links
from app.models import Page
from tests.web import article, html_page

PAGE = "https://blog.test/post"


# --- Finding links in a page ----------------------------------------------


def test_only_article_links_are_found():
    html = html_page(
        article(1), links=["https://other.test/essay", "/notes/spacing"]
    ).encode()

    links = article_links(html, PAGE)

    # The menu (/ and /about) and the footer (twitter.com) are left out
    assert links == ["https://other.test/essay", "https://blog.test/notes/spacing"]


# --- Choosing which links to queue -------------------------------------------


def test_choose_links_filters_and_normalizes():
    chosen = choose_links(
        PAGE,
        [
            "https://blog.test/post#comments",  # the page itself
            "https://other.test/a?utm_source=blog",
            "https://other.test/a",  # same as above after normalizing
            "https://www.youtube.com/watch?v=1",  # video site
            "https://spam.example/win",  # blocklisted
            "https://other.test/paper.PDF",  # a file
            "mailto:me@blog.test",
            "https://third.test/b",
        ],
        frozenset({"spam.example"}),
    )

    assert chosen == ["https://other.test/a", "https://third.test/b"]


def test_choose_links_caps_per_site_and_per_page():
    many_sites = [f"https://site{n}.test/a" for n in range(20)]
    one_site = [f"https://big.test/{n}" for n in range(5)]

    assert len(choose_links(PAGE, one_site, frozenset())) == 3
    assert len(choose_links(PAGE, many_sites, frozenset())) == MAX_LINKS_PER_PAGE


# --- Queuing links from an approved page ---------------------------------------


async def add_page(session_factory, url=PAGE, **fields) -> Page:
    values = {
        "status": "approved",
        "site": url.split("/")[2].removeprefix("www."),
        "outlinks": ["https://other.test/a", "https://third.test/b"],
    }
    async with session_factory() as session:
        page = Page(url=url, canonical_url=url, title="T", **(values | fields))
        session.add(page)
        await session.commit()
        return page


async def share(session_factory, page):
    async with session_factory() as session:
        return await links_to_queue(session, page.id, frozenset())


async def test_approved_page_shares_its_links_once(session_factory):
    page = await add_page(session_factory)

    first = await share(session_factory, page)
    second = await share(session_factory, page)

    assert first == (["https://other.test/a", "https://third.test/b"], 1)
    assert second == ([], 0)


async def test_known_pages_are_not_queued_again(session_factory):
    await add_page(session_factory, "https://other.test/a", outlinks=[])
    page = await add_page(session_factory)

    links, _ = await share(session_factory, page)

    assert links == ["https://third.test/b"]


async def test_full_sites_get_no_more_pages(session_factory):
    async with session_factory() as session:
        for n in range(MAX_PAGES_PER_SITE):
            url = f"https://other.test/old/{n}"
            session.add(Page(url=url, canonical_url=url, title="T", site="other.test"))
        await session.commit()
    page = await add_page(session_factory)

    links, _ = await share(session_factory, page)

    assert links == ["https://third.test/b"]


@pytest.mark.parametrize(
    "fields",
    [
        {"depth": 1},  # found through a link: discovery stops here
        {"status": "pending"},
        {"status": "rejected"},
        {"outlinks": None},
        {"links_queued_at": datetime(2026, 10, 1, tzinfo=UTC)},
    ],
)
async def test_pages_that_dont_share_links(session_factory, fields):
    page = await add_page(session_factory, **fields)

    assert await share(session_factory, page) == ([], 0)
