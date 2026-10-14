import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.orm import undefer

from app.ingestion.fetch import FetchError
from app.ingestion.pipeline import Outcome, ingest_url, ingest_with_retries
from app.models import Page
from tests.web import FakeWeb, article, html_page


@pytest.fixture
def web() -> FakeWeb:
    return FakeWeb()


@pytest.fixture
def fetcher(web, redis):
    return web.fetcher(redis)


async def ingest(session_factory, fetcher, url):
    async with session_factory() as session:
        return await ingest_url(session, fetcher, url)


async def stored_pages(session_factory) -> list[Page]:
    async with session_factory() as session:
        return list(await session.scalars(select(Page)))


async def test_new_page_is_stored_as_pending(session_factory, web, fetcher):
    web.add_html("https://blog.test/post", html_page(article(1), title="Study smarter"))

    result = await ingest(session_factory, fetcher, "https://blog.test/post#top")

    assert result.outcome == Outcome.ADDED
    async with session_factory() as session:
        # content is deferred (not loaded by default), so ask for it
        page = await session.get(Page, result.page_id, options=[undefer(Page.content)])
        assert page.status == "pending"
        assert page.title == "Study smarter"
        assert page.canonical_url == "https://blog.test/post"
        assert page.word_count >= 200
        assert "memory" in page.content or "focus" in page.content
        assert page.simhash is not None
        assert len(page.simhash_bands) == 8
        assert page.embeddable is True
        assert page.last_checked_at is not None


async def test_frame_blocking_headers_are_recorded(session_factory, web, fetcher):
    web.add_html(
        "https://blog.test/post", html_page(article(1)), **{"x-frame-options": "DENY"}
    )

    result = await ingest(session_factory, fetcher, "https://blog.test/post")

    async with session_factory() as session:
        assert (await session.get(Page, result.page_id)).embeddable is False


async def test_same_url_with_tracking_is_a_duplicate(session_factory, web, fetcher):
    web.add_html("https://blog.test/post", html_page(article(1)))
    await ingest(session_factory, fetcher, "https://blog.test/post")

    result = await ingest(
        session_factory, fetcher, "https://BLOG.test/post?utm_source=newsletter"
    )

    assert result.outcome == Outcome.DUPLICATE
    assert web.requests["https://blog.test/post"] == 1  # not fetched again


async def test_canonical_link_reveals_a_duplicate(session_factory, web, fetcher):
    web.add_html("https://blog.test/post", html_page(article(1)))
    web.add_html(
        "https://blog.test/post-print",
        html_page(article(2), canonical="https://blog.test/post"),
    )
    await ingest(session_factory, fetcher, "https://blog.test/post")

    result = await ingest(session_factory, fetcher, "https://blog.test/post-print")

    assert result.outcome == Outcome.DUPLICATE


async def test_canonical_link_to_another_site_is_ignored(session_factory, web, fetcher):
    web.add_html("https://victim.test/post", html_page(article(1)))
    web.add_html(
        "https://copycat.test/post",
        html_page(article(2), canonical="https://victim.test/post"),
    )
    await ingest(session_factory, fetcher, "https://victim.test/post")

    result = await ingest(session_factory, fetcher, "https://copycat.test/post")

    assert result.outcome == Outcome.ADDED
    async with session_factory() as session:
        page = await session.get(Page, result.page_id)
        assert page.canonical_url == "https://copycat.test/post"


async def test_same_article_elsewhere_is_a_near_duplicate(
    session_factory, web, fetcher
):
    text = article(1)
    web.add_html("https://blog.test/post", html_page(text))
    web.add_html(
        "https://mirror.test/copy", html_page(text + " Thanks for reading this post")
    )
    original = await ingest(session_factory, fetcher, "https://blog.test/post")

    result = await ingest(session_factory, fetcher, "https://mirror.test/copy")

    assert result.outcome == Outcome.NEAR_DUPLICATE
    assert str(original.page_id) in result.detail


async def test_different_articles_are_both_added(session_factory, web, fetcher):
    web.add_html("https://blog.test/one", html_page(article(1)))
    web.add_html("https://blog.test/two", html_page(article(2)))

    first = await ingest(session_factory, fetcher, "https://blog.test/one")
    second = await ingest(session_factory, fetcher, "https://blog.test/two")

    assert (first.outcome, second.outcome) == (Outcome.ADDED, Outcome.ADDED)


@pytest.mark.parametrize(
    ("response", "outcome"),
    [
        (httpx.Response(404), Outcome.FETCH_FAILED),
        (
            httpx.Response(
                200, content=b"%PDF-1.7", headers={"content-type": "application/pdf"}
            ),
            Outcome.NOT_HTML,
        ),
        (
            httpx.Response(
                200,
                html=html_page(article(1, words=50)),
                headers={"content-type": "text/html"},
            ),
            Outcome.TOO_SHORT,
        ),
        (
            httpx.Response(
                200,
                html="<html><body></body></html>",
                headers={"content-type": "text/html"},
            ),
            Outcome.NO_CONTENT,
        ),
    ],
)
async def test_unusable_pages_are_not_stored(
    session_factory, web, fetcher, response, outcome
):
    web.add("https://blog.test/page", response)

    result = await ingest(session_factory, fetcher, "https://blog.test/page")

    assert result.outcome == outcome
    assert await stored_pages(session_factory) == []


async def test_unsafe_and_invalid_urls(session_factory, fetcher):
    unsafe = await ingest(session_factory, fetcher, "http://internal.test/")
    invalid = await ingest(session_factory, fetcher, "file:///etc/passwd")

    assert unsafe.outcome == Outcome.UNSAFE_URL
    assert invalid.outcome == Outcome.INVALID_URL


async def test_robots_txt_block_is_an_outcome(session_factory, web, fetcher):
    web.add(
        "https://blog.test/robots.txt",
        httpx.Response(200, text="User-agent: *\nDisallow: /"),
    )

    result = await ingest(session_factory, fetcher, "https://blog.test/post")

    assert result.outcome == Outcome.BLOCKED_BY_ROBOTS


async def test_server_errors_are_retryable(session_factory, web, fetcher):
    web.add("https://blog.test/post", httpx.Response(503))

    with pytest.raises(FetchError) as caught:
        await ingest(session_factory, fetcher, "https://blog.test/post")
    assert caught.value.retryable


async def test_retries_until_the_page_works(session_factory, web, fetcher):
    responses = iter([httpx.Response(503), httpx.Response(503)])
    good = httpx.Response(
        200, html=html_page(article(1)), headers={"content-type": "text/html"}
    )

    def flaky(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        return next(responses, good)

    fetcher.client = httpx.AsyncClient(transport=httpx.MockTransport(flaky))

    result = await ingest_with_retries(
        session_factory, fetcher, "https://blog.test/post", delays=(0, 0)
    )

    assert result.outcome == Outcome.ADDED


async def test_gives_up_after_the_last_retry(session_factory, web, fetcher):
    web.add("https://blog.test/post", httpx.Response(503))

    result = await ingest_with_retries(
        session_factory, fetcher, "https://blog.test/post", delays=(0, 0)
    )

    assert result.outcome == Outcome.FETCH_FAILED
    assert result.detail == "http_503"
    assert web.requests["https://blog.test/post"] == 3
