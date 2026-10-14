"""A fake internet for crawler tests: no real network is ever used."""

import random
from collections import Counter

import httpx

from app.ingestion.fetch import SafeFetcher
from app.ingestion.network import UnsafeUrlError

WORDS = [
    "memory",
    "focus",
    "habit",
    "sleep",
    "review",
    "note",
    "card",
    "spaced",
    "practice",
    "recall",
    "study",
    "learning",
    "brain",
    "attention",
    "schedule",
    "project",
    "deadline",
    "energy",
    "break",
    "rest",
    "goal",
    "plan",
    "reading",
    "writing",
    "summary",
    "question",
    "answer",
    "test",
    "exam",
    "chapter",
    "idea",
]


def article(seed: int, words: int = 400) -> str:
    """A different made-up article for each seed."""
    rng = random.Random(seed)
    return " ".join(rng.choice(WORDS) for _ in range(words))


def html_page(text: str, *, title: str = "A page", canonical: str | None = None) -> str:
    link = f'<link rel="canonical" href="{canonical}">' if canonical else ""
    paragraphs = "".join(
        f"<p>{' '.join(text.split()[i : i + 50])}.</p>"
        for i in range(0, len(text.split()), 50)
    )
    return (
        f"<html><head><title>{title}</title>{link}</head>"
        f"<body><nav>Home About</nav><article><h1>{title}</h1>{paragraphs}"
        "</article><footer>Contact</footer></body></html>"
    )


class FakeWeb:
    """Maps URLs to canned responses and counts requests."""

    def __init__(self) -> None:
        self.routes: dict[str, httpx.Response | Exception] = {}
        self.requests: Counter[str] = Counter()
        self.unsafe_hosts: set[str] = {"internal.test"}

    def add(self, url: str, response: httpx.Response | Exception) -> None:
        self.routes[url] = response

    def add_html(self, url: str, html: str, **headers: str) -> None:
        self.add(
            url,
            httpx.Response(
                200, html=html, headers={"content-type": "text/html", **headers}
            ),
        )

    def redirect(self, url: str, location: str, status: int = 301) -> None:
        self.add(url, httpx.Response(status, headers={"location": location}))

    def handler(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        self.requests[url] += 1
        route = self.routes.get(url, httpx.Response(404))
        if isinstance(route, Exception):
            raise route
        return route

    async def resolver(self, host: str, port: int) -> None:
        if host in self.unsafe_hosts:
            raise UnsafeUrlError(host)

    def fetcher(self, redis) -> SafeFetcher:
        client = httpx.AsyncClient(transport=httpx.MockTransport(self.handler))
        return SafeFetcher(
            client,
            redis,
            user_agent="HopBot/0.1",
            delay_seconds=0.001,
            resolver=self.resolver,
        )
