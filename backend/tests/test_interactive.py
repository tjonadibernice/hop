"""Interactive pages: recognizing them, storing them, mixing them into hops,
and keeping excluded sites (Wikipedia) out."""

import random
from collections import Counter

import pytest
from sqlalchemy import select, update
from sqlalchemy.orm import undefer

from app.config import settings
from app.ingestion import enrich
from app.ingestion.discovery import choose_links
from app.ingestion.exclusions import retire_excluded_pages
from app.ingestion.interactive import Unreadable, page_signals, read_page
from app.ingestion.linkrot import CheckOutcome, recheck_page
from app.ingestion.pipeline import Outcome, ingest_url
from app.ingestion.safety import is_excluded
from app.models import Page
from app.services import hop
from tests.factories import make_page, make_user
from tests.web import FakeWeb, article, html_page

SIMULATION = b"""<html><head><title>The Evolution of Trust</title>
<meta name="description" content="An interactive guide to the game theory of why and how we trust each other.">
</head><body><nav><button>Menu</button></nav><canvas id="stage"></canvas>
<input type="range" min="0" max="10"><input type="checkbox">
<script src="/js/pixi.min.js"></script><script src="/js/main.js"></script></body></html>"""

JS_APP = b"""<html><head><title>Regex tester</title>
<meta name="description" content="Build, test, and debug regular expressions online with live highlighting.">
</head><body><div id="root"></div><script src="/a.js"></script><script src="/b.js"></script></body></html>"""


def blog_with_forms(words: int = 900) -> bytes:
    """A long article with the usual blog furniture: search, newsletter, menu."""
    return (
        "<html><head><title>10 tools I use to plan my week</title></head><body>"
        "<header><button>Menu</button><button>Theme</button></header>"
        '<form><input type="search"><button>Search</button></form>'
        f"<article><h1>Planning</h1><p>{article(7, words)}</p></article>"
        '<form><input type="email"><button>Subscribe</button></form>'
        "</body></html>"
    ).encode()


# --- Recognizing interactive pages ------------------------------------------------


def test_a_simulation_is_interactive_with_a_profile():
    page = read_page(SIMULATION, "https://ncase.example/trust/")

    assert page.kind == "interactive"
    assert page.text.startswith("Interactive page: The Evolution of Trust")
    assert "Description: An interactive guide" in page.text
    assert "1 canvas, 1 slider, 1 other control, uses pixi" in page.text
    assert page.signals.buttons == 0  # the menu button doesn't count


def test_a_javascript_app_is_kept_as_a_candidate():
    page = read_page(JS_APP, "https://regex.example/")

    assert page.kind == "interactive"
    assert page.signals.app_shell
    assert "built with JavaScript" in page.text


def test_an_explorable_essay_is_interactive_despite_its_text():
    html = (
        "<html><head><title>Fourier</title></head><body><article><h1>Fourier</h1>"
        f"<p>{article(3, 900)}</p><canvas></canvas><input type=range><input type=range>"
        "</article><script src='https://cdn.example/d3.v7.min.js'></script></body></html>"
    ).encode()

    assert read_page(html, "https://essay.example/").kind == "interactive"


def test_a_blog_with_forms_and_buttons_stays_an_article():
    page = read_page(blog_with_forms(), "https://blog.example/tools")

    assert page.kind == "article"
    assert page.signals.widgets == 0  # search and email boxes don't count
    assert page.word_count >= 200


def test_short_plain_pages_are_still_refused():
    with pytest.raises(Unreadable) as short:
        read_page(html_page(article(1, 40)), "https://blog.example/stub")
    with pytest.raises(Unreadable) as nameless:
        read_page(
            b"<html><body><canvas></canvas><script src=p5.js></script></body></html>",
            "https://x.example/",
        )

    assert short.value.reason == "too_short"
    assert nameless.value.reason == "no_content"


def test_signals_ignore_broken_html():
    assert page_signals(b"").score == 0


# --- Ingestion, discovery, and link checks ---------------------------------------


@pytest.fixture
def web() -> FakeWeb:
    return FakeWeb()


async def test_interactive_pages_are_stored_with_their_kind(
    session_factory, web, redis
):
    web.add_html("https://ncase.example/trust/", SIMULATION.decode())

    async with session_factory() as session:
        result = await ingest_url(
            session, web.fetcher(redis), "https://ncase.example/trust/"
        )
        page = await session.get(Page, result.page_id, options=[undefer(Page.content)])

    assert result.outcome == Outcome.ADDED
    assert page.kind == "interactive"
    assert page.content.startswith("Interactive page:")


@pytest.mark.parametrize(
    "url",
    [
        "https://en.wikipedia.org/wiki/Spaced_repetition",
        "https://en.m.wikipedia.org/wiki/Hexagon",
        "https://www.wikiwand.com/en/Pomodoro_Technique",
    ],
)
async def test_excluded_sites_are_never_fetched(session_factory, web, redis, url):
    async with session_factory() as session:
        result = await ingest_url(session, web.fetcher(redis), url)

    assert result.outcome == Outcome.EXCLUDED_SITE
    assert sum(web.requests.values()) == 0


async def test_a_redirect_to_an_excluded_site_is_refused(session_factory, web, redis):
    web.redirect("https://short.example/x", "https://en.wikipedia.org/wiki/X")
    web.add_html("https://en.wikipedia.org/wiki/X", html_page(article(1)))

    async with session_factory() as session:
        result = await ingest_url(
            session, web.fetcher(redis), "https://short.example/x"
        )

    assert result.outcome == Outcome.EXCLUDED_SITE


def test_discovery_skips_excluded_sites():
    links = [
        "https://en.wikipedia.org/wiki/A",
        "https://ncase.example/loopy/",
    ]

    assert choose_links("https://blog.example/post", links, frozenset()) == [
        "https://ncase.example/loopy/"
    ]
    assert is_excluded("https://de.wikipedia.org/wiki/B")
    assert not is_excluded("https://notwikipedia.org.example/")


async def test_an_interactive_page_passes_its_link_check(session_factory, web, redis):
    url = "https://ncase.example/trust/"
    web.add_html(url, SIMULATION.decode())
    async with session_factory() as session:
        page = Page(
            url=url,
            canonical_url=url,
            title="Trust",
            status="approved",
            kind="interactive",
        )
        session.add(page)
        await session.commit()

    async with session_factory() as session:
        result = await recheck_page(session, web.fetcher(redis), page.id)

    assert result.outcome == CheckOutcome.ALIVE


async def test_pages_from_excluded_sites_are_retired(session_factory):
    async with session_factory() as session:
        for url, status in [
            ("https://en.wikipedia.org/wiki/A", "approved"),
            ("https://fr.wikipedia.org/wiki/B", "pending"),
            ("https://en.wikipedia.org/wiki/C", "rejected"),
            ("https://ncase.example/", "approved"),
        ]:
            session.add(
                Page(
                    url=url,
                    canonical_url=url,
                    title=url,
                    status=status,
                    site=url.split("/")[2],
                )
            )
        await session.commit()

        retired = await retire_excluded_pages(session)
        statuses = dict(
            (await session.execute(select(Page.url, Page.status_reason))).all()
        )

    assert retired == 2
    assert (
        statuses["https://en.wikipedia.org/wiki/A"]
        == "excluded site (en.wikipedia.org)"
    )
    assert statuses["https://ncase.example/"] is None


# --- Screening -----------------------------------------------------------------


def test_the_screening_prompt_asks_for_the_kind():
    schema = enrich.analysis_schema(["cybersecurity"])

    assert schema["properties"]["kind"]["enum"] == ["interactive", "article"]
    assert "kind" in schema["required"]
    assert "interactive" in enrich.SYSTEM_PROMPT


def test_old_answers_without_a_kind_still_count_as_articles():
    analysis = enrich.PageAnalysis.model_validate(
        {
            "summary": "s",
            "topics": [],
            "quality": 0.5,
            "is_spam": False,
            "is_adult": False,
            "reason": "r",
        }
    )
    assert analysis.kind == "article"


# --- The mix of hops -------------------------------------------------------------


def test_about_seventy_percent_of_hops_are_interactive():
    kinds = Counter(hop.page_kinds(2000, random.Random(1), interactive_percent=70))

    assert 0.66 < kinds["interactive"] / 2000 < 0.74


@pytest.mark.parametrize("percent", [0, 100])
def test_the_mix_can_be_all_one_kind(percent):
    kinds = set(hop.page_kinds(50, random.Random(2), interactive_percent=percent))

    assert kinds == {"interactive" if percent == 100 else "article"}


async def set_kind(session_factory, pages, kind):
    async with session_factory() as session:
        await session.execute(
            update(Page).where(Page.id.in_([p.id for p in pages])).values(kind=kind)
        )
        await session.commit()


@pytest.mark.parametrize("strategy", ["random", "recommender"])
async def test_hops_follow_the_mix(session_factory, topics, monkeypatch, strategy):
    [topic, *_] = topics
    user_id = await make_user(session_factory, topics)
    tools = [await make_page(session_factory, topic, quality=0.9) for _ in range(6)]
    reads = [await make_page(session_factory, topic, quality=0.9) for _ in range(6)]
    await set_kind(session_factory, tools, "interactive")
    monkeypatch.setattr(settings, "interactive_percent", 100)

    async with session_factory() as session:
        picked = await hop._pick(session, user_id, strategy, random.Random(3), 4)

    assert {p.kind for p in picked} == {"interactive"}
    assert len({p.id for p in picked}) == 4
    assert not {p.id for p in picked} & {p.id for p in reads}


async def test_the_other_kind_fills_in_when_one_runs_out(
    session_factory, topics, monkeypatch
):
    [topic, *_] = topics
    user_id = await make_user(session_factory, topics)
    [tool] = [await make_page(session_factory, topic)]
    await set_kind(session_factory, [tool], "interactive")
    for _ in range(4):
        await make_page(session_factory, topic)  # articles
    monkeypatch.setattr(settings, "interactive_percent", 100)

    async with session_factory() as session:
        picked = await hop._pick(session, user_id, "random", random.Random(4), 5)

    assert len(picked) == 5
    assert picked[0].id == tool.id
    assert Counter(p.kind for p in picked) == {"interactive": 1, "article": 4}


async def test_the_api_says_which_kind_a_page_is(
    logged_in_client, session_factory, topics
):
    await logged_in_client.put(
        "/me/interests", json={"topic_ids": [t.id for t in topics]}
    )
    page = await make_page(session_factory, topics[0])
    await set_kind(session_factory, [page], "interactive")

    response = await logged_in_client.post("/hop")

    assert response.status_code == 200
    assert response.json()["kind"] == "interactive"
