import json

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.orm import undefer

from app.ai.embeddings import VoyageEmbedder
from app.ai.llm import ChatProvider, LLMRouter
from app.ingestion.enrich import (
    MAX_CONTENT_CHARS,
    EnrichmentRetryableError,
    EnrichServices,
    PageAnalysis,
    TopicLabel,
    confident_topics,
    enrich_page,
    enrich_with_retries,
    page_prompt,
    route,
)
from app.ingestion.safety import SafetyChecker, SafetyResult
from app.models import EMBEDDING_DIMENSIONS, Page, Topic, page_topics
from tests.web import article

SAFE = SafetyResult(safe=True, checked=True)
GOOD_TOPICS = [TopicLabel(slug="productivity-focus", confidence=0.9)]


def analysis(**changes) -> PageAnalysis:
    values = {
        "summary": "A guide to deep work. It explains how to plan focus blocks.",
        "topics": [{"slug": "productivity-focus", "confidence": 0.9}],
        "quality": 0.8,
        "is_spam": False,
        "is_adult": False,
        "reason": "Clear and practical.",
    }
    return PageAnalysis.model_validate(values | changes)


# --- Routing rules ---------------------------------------------------------


@pytest.mark.parametrize(
    ("page", "safety", "topics", "status", "reason"),
    [
        (analysis(), SAFE, GOOD_TOPICS, "approved", "passed all checks"),
        (
            analysis(),
            SafetyResult(False, True, "blocked domain"),
            GOOD_TOPICS,
            "rejected",
            "blocked domain",
        ),
        (analysis(is_adult=True), SAFE, GOOD_TOPICS, "rejected", "adult content"),
        (analysis(is_spam=True), SAFE, GOOD_TOPICS, "rejected", "spam"),
        (analysis(quality=0.1), SAFE, GOOD_TOPICS, "rejected", "low quality (0.10)"),
        (analysis(), SAFE, [], "needs_review", "no confident topic"),
        (
            analysis(),
            SafetyResult(True, False),
            GOOD_TOPICS,
            "needs_review",
            "safety not checked (no Safe Browsing key)",
        ),
        (
            analysis(quality=0.45),
            SAFE,
            GOOD_TOPICS,
            "needs_review",
            "borderline quality (0.45)",
        ),
    ],
)
def test_route(page, safety, topics, status, reason):
    decision = route(page, safety, topics)
    assert (decision.status, decision.reason) == (status, reason)


def test_confident_topics_filters_and_ranks():
    result = confident_topics(
        analysis(
            topics=[
                {"slug": "cybersecurity", "confidence": 0.65},
                {"slug": "made-up-topic", "confidence": 0.99},
                {"slug": "productivity-focus", "confidence": 1.7},
                {"slug": "habits-routines", "confidence": 0.2},
                {"slug": "cybersecurity", "confidence": 0.7},
            ]
        ),
        {"cybersecurity", "productivity-focus", "habits-routines"},
    )
    assert [(t.slug, t.confidence) for t in result] == [
        ("productivity-focus", 1.0),
        ("cybersecurity", 0.7),
    ]


def test_page_content_is_fenced_and_truncated():
    page = Page(
        url="https://blog.test/post", title="T", content="x" * (MAX_CONTENT_CHARS + 500)
    )
    prompt = page_prompt(page)
    assert prompt.count("x") == MAX_CONTENT_CHARS
    assert "<page_content>" in prompt and prompt.endswith("</page_content>")


# --- Enriching a stored page -------------------------------------------------


class FakeServices:
    """Fake LLM, Voyage, and Safe Browsing servers behind one transport."""

    def __init__(self) -> None:
        self.llm_answer: httpx.Response = self.llm_json(analysis().model_dump())
        self.voyage_answer = httpx.Response(
            200,
            json={"data": [{"index": 0, "embedding": [0.01] * EMBEDDING_DIMENSIONS}]},
        )
        self.safe_browsing_answer = httpx.Response(200, json={})
        self.calls: list[str] = []

    @staticmethod
    def llm_json(data: dict) -> httpx.Response:
        return httpx.Response(
            200, json={"choices": [{"message": {"content": json.dumps(data)}}]}
        )

    def handler(self, request: httpx.Request) -> httpx.Response:
        host = request.url.host
        self.calls.append(host)
        if host == "llm.test":
            return self.llm_answer
        if host == "api.voyageai.com":
            return self.voyage_answer
        if host == "safebrowsing.googleapis.com":
            return self.safe_browsing_answer
        raise AssertionError(f"unexpected request to {host}")

    def services(self, redis, *, safe_browsing_key="sb", voyage=True) -> EnrichServices:
        client = httpx.AsyncClient(transport=httpx.MockTransport(self.handler))
        return EnrichServices(
            llm=LLMRouter(
                client, redis, [ChatProvider("fake", "https://llm.test/v1", "m")]
            ),
            safety=SafetyChecker(
                client, api_key=safe_browsing_key, blocklist=frozenset({"spam.example"})
            ),
            embedder=VoyageEmbedder(client, "v", "voyage-4-lite", EMBEDDING_DIMENSIONS)
            if voyage
            else None,
        )


@pytest.fixture
def fake() -> FakeServices:
    return FakeServices()


async def add_pending_page(session_factory, url="https://blog.test/post") -> Page:
    async with session_factory() as session:
        page = Page(url=url, canonical_url=url, title="Deep work", content=article(3))
        session.add(page)
        await session.commit()
        return page


async def load(session_factory, page_id) -> Page:
    async with session_factory() as session:
        return await session.get(Page, page_id, options=[undefer(Page.embedding)])


async def stored_topics(session_factory, page_id) -> list[tuple[int, float]]:
    async with session_factory() as session:
        rows = await session.execute(
            select(page_topics.c.topic_id, page_topics.c.confidence).where(
                page_topics.c.page_id == page_id
            )
        )
        return list(rows)


async def test_good_page_is_approved_with_everything_saved(
    session_factory, redis, fake
):
    page = await add_pending_page(session_factory)

    async with session_factory() as session:
        result = await enrich_page(session, fake.services(redis), page.id)

    assert (result.status, result.provider) == ("approved", "fake")
    saved = await load(session_factory, page.id)
    assert saved.status == "approved"
    assert saved.status_reason == "passed all checks"
    assert saved.summary.startswith("A guide to deep work")
    assert saved.quality_score == 0.8
    assert len(saved.embedding) == EMBEDDING_DIMENSIONS
    assert saved.enriched_at is not None
    [(_, confidence)] = await stored_topics(session_factory, page.id)
    assert confidence == 0.9


async def test_approved_page_shows_up_in_hop(
    session_factory, redis, fake, logged_in_client
):
    page = await add_pending_page(session_factory)
    async with session_factory() as session:
        await enrich_page(session, fake.services(redis), page.id)
    [(topic_id, _)] = await stored_topics(session_factory, page.id)
    async with session_factory() as session:
        others = list(
            await session.scalars(select(Topic.id).where(Topic.id != topic_id).limit(2))
        )
    await logged_in_client.put("/me/interests", json={"topic_ids": [topic_id, *others]})

    response = await logged_in_client.post("/hop")

    assert response.status_code == 200
    assert response.json()["summary"].startswith("A guide to deep work")


async def test_blocked_domain_is_rejected_without_an_llm_call(
    session_factory, redis, fake
):
    page = await add_pending_page(session_factory, "https://www.spam.example/win")

    async with session_factory() as session:
        result = await enrich_page(session, fake.services(redis), page.id)

    assert (result.status, result.reason) == ("rejected", "blocked domain")
    assert fake.calls == []


async def test_spam_is_rejected_and_not_embedded(session_factory, redis, fake):
    fake.llm_answer = fake.llm_json(analysis(is_spam=True).model_dump())
    page = await add_pending_page(session_factory)

    async with session_factory() as session:
        await enrich_page(session, fake.services(redis), page.id)

    saved = await load(session_factory, page.id)
    assert (saved.status, saved.embedding) == ("rejected", None)
    assert "api.voyageai.com" not in fake.calls


async def test_without_safe_browsing_key_page_needs_review(
    session_factory, redis, fake
):
    page = await add_pending_page(session_factory)

    async with session_factory() as session:
        result = await enrich_page(
            session, fake.services(redis, safe_browsing_key=None), page.id
        )

    assert result.status == "needs_review"


async def test_without_voyage_key_page_is_saved_without_embedding(
    session_factory, redis, fake
):
    page = await add_pending_page(session_factory)

    async with session_factory() as session:
        await enrich_page(session, fake.services(redis, voyage=False), page.id)

    saved = await load(session_factory, page.id)
    assert (saved.status, saved.embedding) == ("approved", None)


async def test_llm_outage_is_retryable_and_leaves_page_pending(
    session_factory, redis, fake
):
    fake.llm_answer = httpx.Response(503)
    page = await add_pending_page(session_factory)

    with pytest.raises(EnrichmentRetryableError):
        async with session_factory() as session:
            await enrich_page(session, fake.services(redis), page.id)

    saved = await load(session_factory, page.id)
    assert (saved.status, saved.enriched_at) == ("pending", None)


async def test_voyage_outage_is_retryable(session_factory, redis, fake):
    fake.voyage_answer = httpx.Response(500)
    page = await add_pending_page(session_factory)

    with pytest.raises(EnrichmentRetryableError):
        async with session_factory() as session:
            await enrich_page(session, fake.services(redis), page.id)


async def test_already_enriched_page_is_skipped(session_factory, redis, fake):
    page = await add_pending_page(session_factory)
    services = fake.services(redis)
    async with session_factory() as session:
        await enrich_page(session, services, page.id)

    async with session_factory() as session:
        assert await enrich_page(session, services, page.id) is None


async def test_retries_until_the_llm_recovers(session_factory, redis, fake):
    answers = iter([httpx.Response(503), httpx.Response(503)])
    good = fake.llm_json(analysis().model_dump())
    original = fake.handler

    def flaky(request):
        if request.url.host == "llm.test":
            fake.calls.append("llm.test")
            return next(answers, good)
        return original(request)

    fake.handler = flaky
    page = await add_pending_page(session_factory)

    result = await enrich_with_retries(
        session_factory, fake.services(redis), page.id, delays=(0, 0)
    )

    assert result.status == "approved"
    assert fake.calls.count("llm.test") == 3
