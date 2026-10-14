import time

import httpx
import pytest

from app.ingestion.fetch import FetchError, RobotsDisallowedError
from app.ingestion.network import UnsafeUrlError
from app.ingestion.politeness import wait_for_turn
from tests.web import FakeWeb


@pytest.fixture
def web() -> FakeWeb:
    return FakeWeb()


async def test_follows_redirects_and_reports_final_url(web, redis):
    web.redirect("https://site.test/old", "/new")
    web.add_html("https://site.test/new", "<p>hi</p>")

    fetched = await web.fetcher(redis).get("https://site.test/old", max_bytes=10_000)

    assert fetched.status_code == 200
    assert fetched.url == "https://site.test/new"


async def test_redirect_to_private_address_is_blocked(web, redis):
    web.redirect("https://site.test/go", "http://internal.test/admin")

    with pytest.raises(UnsafeUrlError):
        await web.fetcher(redis).get("https://site.test/go", max_bytes=10_000)
    assert web.requests["http://internal.test/admin"] == 0


async def test_redirect_loop_stops(web, redis):
    web.redirect("https://site.test/a", "/b")
    web.redirect("https://site.test/b", "/a")

    with pytest.raises(FetchError, match="too_many_redirects"):
        await web.fetcher(redis).get("https://site.test/a", max_bytes=10_000)


async def test_robots_txt_disallow_is_respected(web, redis):
    web.add(
        "https://site.test/robots.txt",
        httpx.Response(200, text="User-agent: *\nDisallow: /private/"),
    )
    web.add_html("https://site.test/public", "<p>ok</p>")
    fetcher = web.fetcher(redis)

    with pytest.raises(RobotsDisallowedError):
        await fetcher.get("https://site.test/private/page", max_bytes=10_000)
    await fetcher.get("https://site.test/public", max_bytes=10_000)
    assert web.requests["https://site.test/private/page"] == 0


async def test_robots_txt_rules_for_our_bot(web, redis):
    web.add(
        "https://site.test/robots.txt",
        httpx.Response(200, text="User-agent: HopBot\nDisallow: /\n"),
    )
    with pytest.raises(RobotsDisallowedError):
        await web.fetcher(redis).get("https://site.test/page", max_bytes=10_000)


async def test_missing_robots_txt_allows_everything(web, redis):
    web.add_html("https://site.test/page", "<p>ok</p>")  # robots.txt is a 404

    fetched = await web.fetcher(redis).get("https://site.test/page", max_bytes=10_000)

    assert fetched.status_code == 200


async def test_robots_txt_server_error_disallows_everything(web, redis):
    web.add("https://site.test/robots.txt", httpx.Response(503))
    web.add_html("https://site.test/page", "<p>ok</p>")

    with pytest.raises(RobotsDisallowedError):
        await web.fetcher(redis).get("https://site.test/page", max_bytes=10_000)


async def test_robots_txt_is_cached(web, redis):
    web.add_html("https://site.test/a", "<p>a</p>")
    web.add_html("https://site.test/b", "<p>b</p>")
    fetcher = web.fetcher(redis)

    await fetcher.get("https://site.test/a", max_bytes=10_000)
    await fetcher.get("https://site.test/b", max_bytes=10_000)

    assert web.requests["https://site.test/robots.txt"] == 1


async def test_large_responses_are_cut_off(web, redis):
    web.add_html("https://site.test/huge", "x" * 50_000)

    with pytest.raises(FetchError, match="too_large"):
        await web.fetcher(redis).get("https://site.test/huge", max_bytes=10_000)


async def test_timeouts_are_retryable(web, redis):
    web.add("https://site.test/slow", httpx.ReadTimeout("too slow"))

    with pytest.raises(FetchError) as caught:
        await web.fetcher(redis).get("https://site.test/slow", max_bytes=10_000)
    assert caught.value.retryable


async def test_requests_to_one_site_are_spaced_out(redis):
    start = time.monotonic()
    for _ in range(3):
        await wait_for_turn(redis, "site.test", delay_seconds=0.1)
    elapsed = time.monotonic() - start

    assert elapsed >= 0.2  # the 2nd and 3rd requests each waited ~0.1 s


async def test_different_sites_dont_wait_for_each_other(redis):
    start = time.monotonic()
    await wait_for_turn(redis, "one.test", delay_seconds=1)
    await wait_for_turn(redis, "two.test", delay_seconds=1)

    assert time.monotonic() - start < 0.5
