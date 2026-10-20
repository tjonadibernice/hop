import time

import httpx
import pytest

from app.ingestion.fetch import (
    FetchError,
    RobotsDisallowedError,
    SafeFetcher,
    pinned_request,
)
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


# --- DNS rebinding: connect to the address that was checked --------------------------


class RebindingDns:
    """A hostile DNS server: a public address first, a private one after."""

    def __init__(self) -> None:
        self.answers = ["93.184.216.34", "10.0.0.5"]
        self.lookups: list[str] = []

    async def resolve(self, host: str, port: int) -> str:
        address = self.answers.pop(0)
        self.lookups.append(address)
        if address.startswith("10."):
            raise UnsafeUrlError(host)
        return address


def recording_fetcher(redis, resolver, handler):
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return SafeFetcher(
        client, redis, user_agent="HopBot/0.1", delay_seconds=0.001, resolver=resolver
    )


async def test_the_connection_goes_to_the_checked_address(redis):
    dns = RebindingDns()
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, html="<p>hi</p>")

    fetcher = recording_fetcher(redis, dns.resolve, handler)
    await fetcher.get(
        "https://rebind.example/page", max_bytes=10_000, check_robots=False
    )

    # One lookup, checked, and the connection went to that very address. The
    # HTTP client never asked DNS again, so the private answer never came.
    assert dns.lookups == ["93.184.216.34"]
    assert [r.url.host for r in seen] == ["93.184.216.34"]
    assert seen[0].headers["host"] == "rebind.example"
    assert seen[0].extensions["sni_hostname"] == "rebind.example"


async def test_every_redirect_hop_is_checked_again(redis):
    dns = RebindingDns()
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(302, headers={"location": "/next"})

    fetcher = recording_fetcher(redis, dns.resolve, handler)
    with pytest.raises(UnsafeUrlError):
        await fetcher.get(
            "https://rebind.example/page", max_bytes=10_000, check_robots=False
        )

    assert dns.lookups == ["93.184.216.34", "10.0.0.5"]
    assert len(seen) == 1  # /next was never requested


async def test_a_pinned_fetch_reports_the_sites_own_url(redis):
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, html="<p>hi</p>")

    async def resolve(host, port):
        return "2606:4700:4700::1111"

    fetcher = recording_fetcher(redis, resolve, handler)
    fetched = await fetcher.get(
        "http://example.org:8080/a?b=1", max_bytes=10_000, check_robots=False
    )

    assert fetched.url == "http://example.org:8080/a?b=1"
    assert str(seen[0].url) == "http://[2606:4700:4700::1111]:8080/a?b=1"
    assert seen[0].headers["host"] == "example.org:8080"
    assert "sni_hostname" not in seen[0].extensions  # plain HTTP has no TLS


def test_pinned_requests_drop_credentials():
    url, headers, extensions = pinned_request(
        "https://user:pw@example.org/x", "93.184.216.34"
    )

    assert url == "https://93.184.216.34/x"
    assert headers == {"Host": "example.org"}
    assert extensions == {"sni_hostname": "example.org"}
