"""Fetch pages safely: SSRF checks, robots.txt, politeness, and size limits."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import httpx
from redis.asyncio import Redis

from app.ingestion.network import ensure_public_host
from app.ingestion.politeness import wait_for_turn

REDIRECT_CODES = {301, 302, 303, 307, 308}
MAX_REDIRECTS = 5
ROBOTS_MAX_BYTES = 500_000  # RFC 9309 asks crawlers to read at least 500 KiB
ROBOTS_CACHE_SECONDS = 24 * 60 * 60
ALLOW_ALL = ""
DISALLOW_ALL = "User-agent: *\nDisallow: /"

Resolver = Callable[[str, int], Awaitable[None]]


class FetchError(Exception):
    """A page couldn't be fetched. retryable=True means trying later may work."""

    def __init__(self, reason: str, *, retryable: bool = False) -> None:
        super().__init__(reason)
        self.reason = reason
        self.retryable = retryable


class RobotsDisallowedError(Exception):
    """The site's robots.txt asks us not to fetch this URL."""


@dataclass(frozen=True)
class Fetched:
    url: str  # final URL, after redirects
    status_code: int
    headers: httpx.Headers
    body: bytes


def _host_and_port(url: str) -> tuple[str, int]:
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise FetchError("unsupported_url")
    return parts.hostname, parts.port or (443 if parts.scheme == "https" else 80)


class SafeFetcher:
    def __init__(
        self,
        client: httpx.AsyncClient,
        redis: Redis,
        *,
        user_agent: str,
        delay_seconds: float = 1.0,
        resolver: Resolver | None = ensure_public_host,
    ) -> None:
        """resolver=None turns off the SSRF check; only for local testing."""
        self.client = client
        self.redis = redis
        self.user_agent = user_agent
        self.delay_seconds = delay_seconds
        self.resolver = resolver

    async def get(
        self, url: str, *, max_bytes: int, check_robots: bool = True
    ) -> Fetched:
        """GET a URL, following redirects one at a time.

        Every hop gets the same checks, so a public page can't redirect us to
        a private address or to a path robots.txt forbids.
        """
        current = url
        for _ in range(MAX_REDIRECTS + 1):
            host, port = _host_and_port(current)
            if self.resolver is not None:
                await self.resolver(host, port)
            if check_robots and not await self.robots_allows(current):
                raise RobotsDisallowedError(current)
            await wait_for_turn(self.redis, host, self.delay_seconds)

            fetched = await self._request(current, max_bytes)
            location = fetched.headers.get("location")
            if fetched.status_code in REDIRECT_CODES and location:
                current = urljoin(current, location)
                continue
            return fetched
        raise FetchError("too_many_redirects")

    async def _request(self, url: str, max_bytes: int) -> Fetched:
        try:
            async with self.client.stream(
                "GET", url, headers={"User-Agent": self.user_agent}
            ) as response:
                # Read in chunks and stop early, so a huge file can't fill memory
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    body += chunk
                    if len(body) > max_bytes:
                        raise FetchError("too_large")
                return Fetched(
                    str(response.url),
                    response.status_code,
                    response.headers,
                    bytes(body),
                )
        except httpx.TimeoutException as error:
            raise FetchError("timeout", retryable=True) from error
        except httpx.HTTPError as error:
            raise FetchError("network_error", retryable=True) from error

    async def robots_allows(self, url: str) -> bool:
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        key = f"robots:{origin}"
        rules = await self.redis.get(key)
        if rules is None:
            rules = await self._load_robots(origin)
            await self.redis.set(key, rules, ex=ROBOTS_CACHE_SECONDS)

        parser = RobotFileParser()
        parser.parse(rules.splitlines())
        parser.modified()  # mark as loaded; can_fetch() refuses everything otherwise
        return parser.can_fetch(self.user_agent, url)

    async def _load_robots(self, origin: str) -> str:
        """The site's robots.txt rules, following RFC 9309 for missing files."""
        try:
            response = await self.get(
                f"{origin}/robots.txt", max_bytes=ROBOTS_MAX_BYTES, check_robots=False
            )
        except FetchError:
            return DISALLOW_ALL  # unreachable: assume we may not crawl
        if response.status_code >= 500:
            return DISALLOW_ALL  # server error: assume we may not crawl
        if response.status_code >= 400:
            return ALLOW_ALL  # no robots.txt: everything is allowed
        return response.body.decode("utf-8", errors="replace")
