"""Review one needs_review page with the curator agent and apply the result."""

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from langchain_core.messages import HumanMessage, SystemMessage
from sqlalchemy import delete, insert, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload, undefer

from app.ai.llm import AllProvidersFailedError
from app.curator.graph import build_graph, initial_state, recursion_limit
from app.curator.model import AgentModel
from app.curator.policy import PolicyOutcome, apply_policy
from app.curator.prompts import page_message, system_prompt
from app.curator.tools import CuratorToolbox, PageFacts
from app.ingestion.enrich import FIRST_LINK_CHECK_AFTER
from app.ingestion.fetch import SafeFetcher
from app.ingestion.safety import SafetyChecker, SafetyCheckError
from app.models import CuratorReview, Page, Topic, page_topics

logger = logging.getLogger(__name__)


class CuratorRetryableError(Exception):
    """A service failed (every LLM busy, Safe Browsing down). The page stays
    uncurated, and the hourly sweep tries again."""

    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


@dataclass
class CuratorServices:
    model: AgentModel
    safety: SafetyChecker
    fetcher: SafeFetcher | None  # None: no live fetching (tests, offline)
    max_turns: int = 8
    max_tool_calls: int = 6


@dataclass(frozen=True)
class CurationResult:
    page_id: uuid.UUID
    proposed: str
    status: str
    reason: str
    blocked_by: str | None
    provider: str | None
    tool_calls: int


async def curate_page(
    session_factory: async_sessionmaker[AsyncSession],
    services: CuratorServices,
    page_id: uuid.UUID,
) -> CurationResult | None:
    """Review one page. None if it's gone or no longer waiting for review."""
    async with session_factory() as session:
        page = await session.get(
            Page,
            page_id,
            options=[
                undefer(Page.content),
                undefer(Page.embedding),
                selectinload(Page.topics),
            ],
        )
        if page is None or page.status != "needs_review":
            return None
        facts = PageFacts.from_page(page)
        topics = {t.slug: t.name for t in await session.scalars(select(Topic))}

    toolbox = CuratorToolbox(session_factory, services.safety, services.fetcher, facts)
    graph = build_graph(
        services.model,
        toolbox,
        max_turns=services.max_turns,
        max_tool_calls=services.max_tool_calls,
    )
    messages = [
        SystemMessage(content=system_prompt(topics, services.max_tool_calls)),
        HumanMessage(content=page_message(facts)),
    ]
    try:
        state = await graph.ainvoke(
            initial_state(messages),
            {"recursion_limit": recursion_limit(services.max_turns)},
        )
    except AllProvidersFailedError as error:
        raise CuratorRetryableError(
            f"LLM: {error}", retry_after=error.retry_after
        ) from error

    # The guardrails use a fresh safety result, never the agent's word for it
    safety = toolbox.safety_result
    if safety is None:
        try:
            safety = await services.safety.check(facts.url)
        except SafetyCheckError as error:
            raise CuratorRetryableError(f"safety check: {error}") from error

    outcome = apply_policy(
        state["proposal"],
        safety=safety,
        known_topics=set(topics),
        stop_reason=state["stop_reason"],
    )
    saved = await _save(session_factory, facts.id, outcome, state)
    if not saved:
        return None
    return CurationResult(
        page_id=facts.id,
        proposed=outcome.proposed,
        status=outcome.status,
        reason=outcome.reason,
        blocked_by=outcome.blocked_by,
        provider=state["provider"],
        tool_calls=state["tool_calls"],
    )


async def _save(
    session_factory: async_sessionmaker[AsyncSession],
    page_id: uuid.UUID,
    outcome: PolicyOutcome,
    state: dict,
) -> bool:
    """Apply the outcome and keep the audit trail, in one transaction."""
    async with session_factory() as session:
        page = await session.get(Page, page_id, with_for_update=True)
        if page is None or page.status != "needs_review":
            # Something else decided while the agent was thinking (a person,
            # or a link check). Their decision stands.
            return False
        now = datetime.now(UTC)
        page.status = outcome.status
        page.status_reason = outcome.reason[:300]
        page.curated_at = now
        if outcome.status == "approved":
            page.quality_score = outcome.quality
            page.next_check_at = now + FIRST_LINK_CHECK_AFTER
            topic_ids = dict(
                (
                    await session.execute(
                        select(Topic.slug, Topic.id).where(
                            Topic.slug.in_(outcome.topics)
                        )
                    )
                ).all()
            )
            await session.execute(
                delete(page_topics).where(page_topics.c.page_id == page.id)
            )
            # No confidence: these topics were chosen by the curator
            await session.execute(
                insert(page_topics),
                [
                    {"page_id": page.id, "topic_id": topic_ids[slug]}
                    for slug in outcome.topics
                ],
            )
        session.add(
            CuratorReview(
                page_id=page.id,
                proposed=outcome.proposed,
                outcome=outcome.status,
                reason=outcome.reason,
                blocked_by=outcome.blocked_by,
                topics=outcome.topics,
                quality=outcome.quality,
                provider=state["provider"],
                steps=state["steps"],
            )
        )
        await session.commit()
    return True


async def uncurated_page_ids(
    session: AsyncSession, limit: int | None = None
) -> list[uuid.UUID]:
    """needs_review pages the curator hasn't looked at yet, oldest first."""
    return list(
        await session.scalars(
            select(Page.id)
            .where(Page.status == "needs_review", Page.curated_at.is_(None))
            .order_by(Page.created_at)
            .limit(limit)
        )
    )
