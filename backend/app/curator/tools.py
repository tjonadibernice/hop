"""The curator's tools: read-only lookups the agent can ask for.

None of them can change anything. The only way the agent affects a page is
submit_decision, and even that goes through the guardrails in policy.py.
Every result that contains text from the web is fenced, as in enrichment,
so the model can tell data from instructions.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from app.ai.untrusted import fence, injection_signals
from app.ingestion.fetch import FetchError, RobotsDisallowedError, SafeFetcher
from app.ingestion.interactive import INTERACTIVE, Unreadable, read_page
from app.ingestion.network import HostNotFoundError, UnsafeUrlError
from app.ingestion.pipeline import HTML_TYPES, MAX_PAGE_BYTES
from app.ingestion.safety import SafetyChecker, SafetyCheckError, SafetyResult
from app.ingestion.simhash import from_signed, hamming_distance, simhash
from app.ingestion.urls import site_of
from app.models import Page

SIMILAR_PAGES = 5
SITE_EXAMPLES = 3
LIVE_EXCERPT_CHARS = 1500


class SubmitDecision(BaseModel):
    """The agent's final answer. Checked by the guardrails before it's applied."""

    decision: Literal["approve", "reject", "escalate"]
    topics: list[str] = Field(default_factory=list, max_length=3)
    quality: float = Field(ge=0, le=1)
    reason: str = Field(min_length=1, max_length=300)


def _function(
    name: str, description: str, parameters: dict[str, Any] | None = None
) -> dict:
    function: dict[str, Any] = {"name": name, "description": description}
    # A tool without arguments has no "parameters" at all: Gemini refuses an
    # object schema with an empty "properties"
    if parameters is not None:
        function["parameters"] = parameters
    return {"type": "function", "function": function}


# Written out by hand (not generated from the models) so every provider gets
# the same simple schema. It sticks to the part of JSON Schema that Gemini
# accepts for tools: no "additionalProperties", no "$ref", no empty objects.
# submit_decision's arguments are validated by SubmitDecision anyway.
TOOL_SPECS = [
    _function(
        "site_history",
        "How Hop has judged other pages from the same website: counts by "
        "status and a few example titles.",
    ),
    _function(
        "similar_pages",
        "The approved pages most similar to this one, with their topics. "
        "Shows whether the page fits a topic and how it compares.",
    ),
    _function(
        "check_safety",
        "Run the safety check again: Hop's domain blocklist and Google Safe "
        "Browsing (if configured).",
    ),
    _function(
        "fetch_live_page",
        "Fetch the page again now: whether it still loads, where it redirects, "
        "how much its text changed since it was stored, and a short excerpt.",
    ),
    _function(
        "submit_decision",
        "Your final decision. Call it exactly once, after gathering evidence.",
        {
            "type": "object",
            "properties": {
                "decision": {
                    "type": "string",
                    "enum": ["approve", "reject", "escalate"],
                },
                "topics": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Up to 3 topic slugs from the allowed list",
                },
                "quality": {
                    "type": "number",
                    "description": "0 to 1, as defined in your instructions",
                },
                "reason": {
                    "type": "string",
                    "description": "One or two sentences a person can check",
                },
            },
            "required": ["decision", "topics", "quality", "reason"],
        },
    ),
]
TOOL_NAMES = {spec["function"]["name"] for spec in TOOL_SPECS}


@dataclass(frozen=True)
class PageFacts:
    """What the curator knows about the page under review, loaded once."""

    id: uuid.UUID
    url: str
    title: str
    summary: str | None
    content: str
    status_reason: str | None
    quality_score: float | None
    simhash: int | None
    embedding: list[float] | None
    topics: list[str] = field(default_factory=list)
    kind: str = "article"  # or "interactive": then content is a profile

    @property
    def site(self) -> str:
        return site_of(self.url)

    @classmethod
    def from_page(cls, page: Page) -> "PageFacts":
        return cls(
            id=page.id,
            url=page.url,
            title=page.title,
            summary=page.summary,
            content=page.content or "",
            status_reason=page.status_reason,
            quality_score=page.quality_score,
            simhash=page.simhash,
            embedding=list(page.embedding) if page.embedding is not None else None,
            topics=[topic.slug for topic in page.topics],
            kind=page.kind,
        )


class Toolbox(Protocol):
    """What the agent's graph needs from a toolbox."""

    safety_result: SafetyResult | None
    # Signs of prompt injection in what the tools fetched (the live page)
    injection_signals: list[str]

    async def call(self, name: str, args: dict[str, Any]) -> str: ...


# How each tool reports what it found. Shared with the evaluation's scripted
# toolbox (app/curator/evaluation.py), so the model sees the same wording there.


def site_history_report(
    site: str, counts: dict[str, int], examples: Sequence[str]
) -> str:
    summary = (
        f"Other pages from {site}: {counts.get('approved', 0)} approved, "
        f"{counts.get('rejected', 0)} rejected, "
        f"{counts.get('needs_review', 0)} waiting for review, "
        f"{counts.get('dead', 0)} dead, {counts.get('pending', 0)} pending."
    )
    if not examples:
        return summary
    return summary + "\n" + fence("untrusted_titles", "\n".join(examples))


def similar_pages_report(rows: Sequence[tuple[float, str, Sequence[str]]]) -> str:
    """rows: (similarity from 0 to 1, title, topic slugs), most similar first."""
    if not rows:
        return "No approved pages with embeddings to compare with yet."
    lines = [
        f"{similarity:.2f} similar: {title} [{', '.join(topics) or 'no topic'}]"
        for similarity, title, topics in rows
    ]
    return "Most similar approved pages (1.00 = identical):\n" + fence(
        "untrusted_titles", "\n".join(lines)
    )


def safety_report(result: SafetyResult) -> str:
    if not result.safe:
        return f"UNSAFE: {result.reason or 'flagged'}."
    if not result.checked:
        return (
            "Not on Hop's blocklist, but Safe Browsing isn't configured, "
            "so the page can't be approved."
        )
    return "Safe: not on the blocklist, and Safe Browsing found no threats."


def unknown_tool_report(name: str) -> str:
    return f"Unknown tool {name!r}. Available: {', '.join(sorted(TOOL_NAMES))}."


NO_EMBEDDING = "This page has no embedding, so similar pages can't be looked up."
NO_LIVE_FETCH = "Live fetching isn't available here."


def live_page_report(facts: Sequence[str], excerpt: str | None = None) -> str:
    """facts: short findings such as "HTTP 200"; excerpt: the live text, if any."""
    report = "; ".join(facts) + "."
    if excerpt is None:
        return report
    return report + "\n" + fence("page_content", excerpt[:LIVE_EXCERPT_CHARS])


class CuratorToolbox:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        safety: SafetyChecker,
        fetcher: SafeFetcher | None,
        page: PageFacts,
    ) -> None:
        self.session_factory = session_factory
        self.safety = safety
        self.fetcher = fetcher
        self.page = page
        # The latest safety result, reused by the guardrails if the agent
        # already asked for it (saves a second Safe Browsing call)
        self.safety_result: SafetyResult | None = None
        self.injection_signals: list[str] = []

    async def call(self, name: str, args: dict[str, Any]) -> str:
        """Run one tool by name. Unknown names get an error message, not an exception."""
        match name:
            case "site_history":
                return await self.site_history()
            case "similar_pages":
                return await self.similar_pages()
            case "check_safety":
                return await self.check_safety()
            case "fetch_live_page":
                return await self.fetch_live_page()
        return unknown_tool_report(name)

    async def site_history(self) -> str:
        site = self.page.site
        async with self.session_factory() as session:
            counts = dict(
                (
                    await session.execute(
                        select(Page.status, func.count())
                        .where(Page.site == site, Page.id != self.page.id)
                        .group_by(Page.status)
                    )
                ).all()
            )
            examples = []
            for status in ("approved", "rejected"):
                rows = await session.execute(
                    select(Page.title, Page.status_reason)
                    .where(Page.site == site, Page.status == status)
                    .where(Page.id != self.page.id)
                    .order_by(Page.created_at.desc())
                    .limit(SITE_EXAMPLES)
                )
                for title, reason in rows:
                    note = f" (reason: {reason})" if status == "rejected" else ""
                    examples.append(f"{status}: {title}{note}")

        return site_history_report(site, counts, examples)

    async def similar_pages(self) -> str:
        if self.page.embedding is None:
            return NO_EMBEDDING
        distance = Page.embedding.cosine_distance(self.page.embedding)
        async with self.session_factory() as session:
            rows = (
                await session.execute(
                    select(Page, distance)
                    .where(Page.status == "approved", Page.id != self.page.id)
                    .where(Page.embedding.is_not(None))
                    .order_by(distance)
                    .limit(SIMILAR_PAGES)
                    .options(selectinload(Page.topics))
                )
            ).all()
        return similar_pages_report(
            [(1 - d, page.title, [t.slug for t in page.topics]) for page, d in rows]
        )

    async def check_safety(self) -> str:
        try:
            result = await self.safety.check(self.page.url)
        except SafetyCheckError as error:
            return f"The safety check couldn't run right now ({error})."
        self.safety_result = result
        return safety_report(result)

    async def fetch_live_page(self) -> str:
        if self.fetcher is None:
            return NO_LIVE_FETCH
        try:
            fetched = await self.fetcher.get(self.page.url, max_bytes=MAX_PAGE_BYTES)
        except RobotsDisallowedError:
            return "robots.txt now blocks Hop from this page."
        except UnsafeUrlError:
            return "The page now points to a private address."
        except HostNotFoundError:
            return "The website's host name no longer exists."
        except FetchError as error:
            return f"The page couldn't be fetched ({error.reason})."

        facts = [f"HTTP {fetched.status_code}"]
        if site_of(fetched.url) != self.page.site:
            facts.append(f"redirects to another site: {site_of(fetched.url)}")
        if fetched.status_code >= 400:
            return live_page_report(facts)
        content_type = (
            fetched.headers.get("content-type", "").split(";")[0].strip().lower()
        )
        if content_type not in HTML_TYPES:
            return live_page_report(facts + [f"not HTML ({content_type or 'unknown'})"])
        try:
            page_read = read_page(fetched.body, fetched.url)
        except Unreadable:
            return live_page_report(facts + ["no readable content"])

        self.injection_signals = injection_signals(page_read.text)
        if page_read.kind == INTERACTIVE:
            facts.append(f"interactive page ({page_read.signals.summary()})")
        else:
            facts.append(f"{page_read.word_count} words")
        if self.page.simhash is not None:
            changed = hamming_distance(
                simhash(page_read.text), from_signed(self.page.simhash)
            )
            facts.append(f"text differs from the stored copy by {changed} of 64 bits")
        return live_page_report(facts, page_read.text)
