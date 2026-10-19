from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy.orm import undefer

from app.ingestion.linkrot import (
    MAX_FAILURES,
    RECHECK_INTERVAL,
    RETRY_AFTER_FAILURE,
    CheckOutcome,
    due_page_ids,
    recheck_page,
)
from app.ingestion.simhash import simhash, to_signed
from app.models import Page
from tests.web import FakeWeb, article, html_page

NOW = datetime(2026, 10, 16, 3, 0, tzinfo=UTC)
URL = "https://blog.test/post"


@pytest.fixture
def web() -> FakeWeb:
    return FakeWeb()


@pytest.fixture
def fetcher(web, redis):
    return web.fetcher(redis)


async def add_page(session_factory, url=URL, **fields) -> Page:
    values = {"status": "approved", "simhash": to_signed(simhash(article(5)))}
    async with session_factory() as session:
        page = Page(url=url, canonical_url=url, title="A post", **(values | fields))
        session.add(page)
        await session.commit()
        return page


async def check(session_factory, fetcher, page):
    async with session_factory() as session:
        return await recheck_page(session, fetcher, page.id, now=NOW)


async def load(session_factory, page) -> Page:
    async with session_factory() as session:
        return await session.get(Page, page.id)


# --- Which pages are due -----------------------------------------------------


async def test_due_pages_are_approved_and_past_their_date(session_factory):
    never = await add_page(session_factory, "https://a.test/never")
    overdue = await add_page(
        session_factory, "https://a.test/overdue", next_check_at=NOW - timedelta(days=1)
    )
    await add_page(
        session_factory, "https://a.test/later", next_check_at=NOW + timedelta(days=1)
    )
    await add_page(session_factory, "https://a.test/pending", status="pending")
    await add_page(session_factory, "https://a.test/dead", status="dead")

    async with session_factory() as session:
        due = await due_page_ids(session, NOW)

    assert due == [never.id, overdue.id]  # never-checked pages first


async def test_due_pages_respect_the_batch_size(session_factory):
    for number in range(3):
        await add_page(session_factory, f"https://a.test/{number}")

    async with session_factory() as session:
        assert len(await due_page_ids(session, NOW, limit=2)) == 2


# --- Checking one page --------------------------------------------------------


async def test_working_page_is_checked_again_in_30_days(session_factory, web, fetcher):
    web.add_html(URL, html_page(article(5)), **{"x-frame-options": "DENY"})
    page = await add_page(session_factory, check_failures=2, embeddable=True)

    result = await check(session_factory, fetcher, page)

    assert result.outcome == CheckOutcome.ALIVE
    saved = await load(session_factory, page)
    assert saved.status == "approved"
    assert saved.check_failures == 0
    assert saved.last_checked_at == NOW
    assert saved.next_check_at == NOW + RECHECK_INTERVAL
    assert saved.embeddable is False  # the site started blocking iframes


async def test_seed_page_gets_a_fingerprint_on_its_first_check(
    session_factory, web, fetcher
):
    web.add_html(URL, html_page(article(5)))
    page = await add_page(session_factory, simhash=None)

    await check(session_factory, fetcher, page)

    async with session_factory() as session:
        saved = await session.get(Page, page.id, options=[undefer(Page.outlinks)])
    assert saved.simhash is not None
    assert len(saved.simhash_bands) == 8
    assert saved.outlinks == []  # links kept so discovery can use them


async def test_failures_are_retried_then_the_page_dies(session_factory, web, fetcher):
    web.add(URL, httpx.Response(404))
    page = await add_page(session_factory)

    first = await check(session_factory, fetcher, page)
    saved = await load(session_factory, page)
    assert first.outcome == CheckOutcome.FAILED
    assert (saved.status, saved.check_failures) == ("approved", 1)
    assert saved.next_check_at == NOW + RETRY_AFTER_FAILURE

    for _ in range(MAX_FAILURES - 1):
        last = await check(session_factory, fetcher, page)

    saved = await load(session_factory, page)
    assert last.outcome == CheckOutcome.DEAD
    assert saved.status == "dead"
    assert saved.status_reason == "failed 3 checks in a row (HTTP 404)"
    assert saved.next_check_at is None


async def test_one_success_resets_the_failure_count(session_factory, web, fetcher):
    web.add_html(URL, html_page(article(5)))
    page = await add_page(session_factory, check_failures=MAX_FAILURES - 1)

    await check(session_factory, fetcher, page)

    assert (await load(session_factory, page)).check_failures == 0


async def test_timeouts_count_as_failures(session_factory, web, fetcher):
    web.add(URL, httpx.ReadTimeout("slow"))
    page = await add_page(session_factory)

    result = await check(session_factory, fetcher, page)

    assert (result.outcome, result.reason) == (CheckOutcome.FAILED, "timeout")


@pytest.mark.parametrize(
    ("setup", "reason"),
    [
        (lambda web: web.add(URL, httpx.Response(410)), "gone (HTTP 410)"),
        (
            lambda web: web.add(
                "https://blog.test/robots.txt",
                httpx.Response(200, text="User-agent: *\nDisallow: /"),
            ),
            "robots.txt now blocks Hop",
        ),
        (
            lambda web: web.redirect(URL, "http://internal.test/"),
            "now points to a private address",
        ),
    ],
)
async def test_some_answers_mean_dead_right_away(
    session_factory, web, fetcher, setup, reason
):
    setup(web)
    page = await add_page(session_factory)

    result = await check(session_factory, fetcher, page)

    assert (result.outcome, result.reason) == (CheckOutcome.DEAD, reason)
    assert (await load(session_factory, page)).status == "dead"


async def test_redirect_to_another_site_needs_review(session_factory, web, fetcher):
    web.redirect(URL, "https://parked-domains.test/sale")
    web.add_html("https://parked-domains.test/sale", html_page(article(5)))
    page = await add_page(session_factory)

    result = await check(session_factory, fetcher, page)

    assert result.outcome == CheckOutcome.CHANGED
    saved = await load(session_factory, page)
    assert (saved.status, saved.status_reason) == (
        "needs_review",
        "now redirects to parked-domains.test",
    )


async def test_redirect_to_www_is_not_a_move(session_factory, web, fetcher):
    web.redirect(URL, "https://www.blog.test/post")
    web.add_html("https://www.blog.test/post", html_page(article(5)))
    page = await add_page(session_factory)

    result = await check(session_factory, fetcher, page)

    assert result.outcome == CheckOutcome.ALIVE


async def test_replaced_content_needs_review(session_factory, web, fetcher):
    web.add_html(URL, html_page(article(99)))  # a completely different text
    page = await add_page(session_factory)

    result = await check(session_factory, fetcher, page)

    assert result.outcome == CheckOutcome.CHANGED
    assert (await load(session_factory, page)).status_reason.startswith(
        "content changed"
    )


async def test_small_edits_are_fine(session_factory, web, fetcher):
    web.add_html(URL, html_page(article(5) + " Updated in 2026 with new examples."))
    page = await add_page(session_factory)

    assert (await check(session_factory, fetcher, page)).outcome == CheckOutcome.ALIVE


async def test_pages_that_arent_approved_are_skipped(session_factory, fetcher):
    page = await add_page(session_factory, status="rejected")

    assert await check(session_factory, fetcher, page) is None
