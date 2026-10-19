"""What admins can do from the review screen, and the rules around it.

Every action is recorded in review_actions (who, what, when, why), so a
page's history can always be explained.

- approve: a needs_review or rejected page goes live, with 1-3 topics the
  admin chose. A person may overrule the curator and the automatic rules.
- reject: a needs_review page is turned down.
- remove: any page leaves Hop right away ("Remove from Hop"). Its row and
  history stay, so it isn't crawled again.
- purge: for takedowns. The text, summary, embedding, links, and the
  curator's excerpts are erased. The URL and the SimHash fingerprint stay as
  a tombstone, so neither the page nor a near-copy of it can come back.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import delete, insert, or_, select, update
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload, undefer

from app.ingestion.enrich import FIRST_LINK_CHECK_AFTER, MAX_TOPICS
from app.models import CuratorReview, Page, ReviewAction, Topic, User, page_topics

EXCERPT_CHARS = 1500
PURGED_TITLE = "[purged]"


class ReviewError(Exception):
    """An action that can't be done; the message is safe to show the admin."""


class PageNotFoundError(ReviewError):
    pass


class ActionNotAllowedError(ReviewError):
    pass


class UnknownTopicError(ReviewError):
    pass


@dataclass(frozen=True)
class PageDetail:
    page: Page
    excerpt: str | None
    reviews: Sequence[CuratorReview]
    actions: Sequence[ReviewAction]


def _escape_like(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


async def latest_reviews(
    session: AsyncSession, page_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, CuratorReview]:
    """The newest curator review for each page, if it has one."""
    if not page_ids:
        return {}
    rows = await session.scalars(
        select(CuratorReview)
        .where(CuratorReview.page_id.in_(page_ids))
        .ext(distinct_on(CuratorReview.page_id))
        .order_by(CuratorReview.page_id, CuratorReview.id.desc())
    )
    return {review.page_id: review for review in rows}


async def review_queue(
    session: AsyncSession, *, escalated_only: bool = True, limit: int = 50
) -> Sequence[Page]:
    """needs_review pages, oldest first.

    escalated_only: just the pages the curator has looked at and handed to a
    person (the others may still be decided by the curator).
    """
    query = (
        select(Page)
        .where(Page.status == "needs_review", Page.purged_at.is_(None))
        .order_by(Page.created_at)
        .limit(limit)
        .options(selectinload(Page.topics))
    )
    if escalated_only:
        query = query.where(Page.curated_at.is_not(None))
    return (await session.scalars(query)).all()


async def search_pages(
    session: AsyncSession, text: str, limit: int = 20
) -> Sequence[Page]:
    """Pages of any status whose URL or title contains the text."""
    pattern = f"%{_escape_like(text.strip())}%"
    return (
        await session.scalars(
            select(Page)
            .where(
                or_(
                    Page.url.ilike(pattern, escape="\\"),
                    Page.title.ilike(pattern, escape="\\"),
                )
            )
            .order_by(Page.created_at.desc())
            .limit(limit)
            .options(selectinload(Page.topics))
        )
    ).all()


async def page_detail(session: AsyncSession, page_id: uuid.UUID) -> PageDetail:
    page = await session.get(
        Page,
        page_id,
        options=[undefer(Page.content), selectinload(Page.topics)],
        populate_existing=True,
    )
    if page is None:
        raise PageNotFoundError("Page not found.")
    reviews = (
        await session.scalars(
            select(CuratorReview)
            .where(CuratorReview.page_id == page_id)
            .order_by(CuratorReview.id.desc())
        )
    ).all()
    actions = (
        await session.scalars(
            select(ReviewAction)
            .where(ReviewAction.page_id == page_id)
            .order_by(ReviewAction.id.desc())
        )
    ).all()
    excerpt = page.content[:EXCERPT_CHARS] if page.content else None
    return PageDetail(page, excerpt, reviews, actions)


async def _locked_page(session: AsyncSession, page_id: uuid.UUID) -> Page:
    """The page, locked until commit, so two admins (or an admin and the
    curator) can't change it at the same moment."""
    page = await session.get(Page, page_id, with_for_update=True)
    if page is None:
        raise PageNotFoundError("Page not found.")
    if page.purged_at is not None:
        raise ActionNotAllowedError("This page was purged; nothing more can be done.")
    return page


def _record(
    session: AsyncSession,
    page: Page,
    admin: User,
    action: str,
    from_status: str,
    reason: str | None,
    topics: Sequence[str] = (),
) -> None:
    session.add(
        ReviewAction(
            page_id=page.id,
            actor_id=admin.id,
            actor_email=admin.email,
            action=action,
            from_status=from_status,
            to_status=page.status,
            reason=reason,
            topics=list(topics),
        )
    )


def _status_reason(verb: str, admin: User, reason: str | None) -> str:
    text = f"{verb} by {admin.email}"
    return (f"{text}: {reason}" if reason else text)[:300]


async def approve(
    session: AsyncSession,
    admin: User,
    page_id: uuid.UUID,
    topic_slugs: Sequence[str],
    reason: str | None = None,
) -> None:
    page = await _locked_page(session, page_id)
    if page.status not in ("needs_review", "rejected"):
        raise ActionNotAllowedError(
            f"Only pages waiting for review or rejected pages can be approved (this one is {page.status})."
        )
    slugs = list(dict.fromkeys(topic_slugs))
    if not 1 <= len(slugs) <= MAX_TOPICS:
        raise UnknownTopicError(f"Choose 1 to {MAX_TOPICS} topics.")
    topic_ids = dict(
        (
            await session.execute(
                select(Topic.slug, Topic.id).where(Topic.slug.in_(slugs))
            )
        ).all()
    )
    if len(topic_ids) != len(slugs):
        raise UnknownTopicError("Unknown topic.")

    from_status = page.status
    now = datetime.now(UTC)
    page.status = "approved"
    page.status_reason = _status_reason("approved", admin, reason)
    page.next_check_at = now + FIRST_LINK_CHECK_AFTER
    await session.execute(delete(page_topics).where(page_topics.c.page_id == page.id))
    # No confidence: a person chose these topics
    await session.execute(
        insert(page_topics),
        [{"page_id": page.id, "topic_id": topic_ids[slug]} for slug in slugs],
    )
    _record(session, page, admin, "approve", from_status, reason, slugs)
    await session.commit()


async def reject(
    session: AsyncSession, admin: User, page_id: uuid.UUID, reason: str
) -> None:
    page = await _locked_page(session, page_id)
    if page.status != "needs_review":
        raise ActionNotAllowedError(
            f"Only pages waiting for review can be rejected (this one is {page.status}). Use Remove from Hop instead."
        )
    from_status = page.status
    page.status = "rejected"
    page.status_reason = _status_reason("rejected", admin, reason)
    _record(session, page, admin, "reject", from_status, reason)
    await session.commit()


async def remove(
    session: AsyncSession, admin: User, page_id: uuid.UUID, reason: str
) -> None:
    """Take any page out of Hop. Queued hops skip it (they re-check the status)."""
    page = await _locked_page(session, page_id)
    if page.status == "rejected":
        raise ActionNotAllowedError("This page is already out of Hop.")
    from_status = page.status
    page.status = "rejected"
    page.status_reason = _status_reason("removed", admin, reason)
    page.next_check_at = None
    _record(session, page, admin, "remove", from_status, reason)
    await session.commit()


async def purge(
    session: AsyncSession,
    admin: User,
    page_id: uuid.UUID,
    reason: str,
    confirm_url: str,
) -> None:
    page = await _locked_page(session, page_id)
    if confirm_url.strip() != page.url:
        raise ActionNotAllowedError("To purge, type the page's exact URL to confirm.")
    from_status = page.status
    now = datetime.now(UTC)
    # Erase everything that came from the page itself
    page.title = PURGED_TITLE
    page.summary = None
    page.content = None
    page.outlinks = None
    page.embedding = None
    page.word_count = None
    page.quality_score = None
    page.embeddable = None
    page.next_check_at = None
    # Kept on purpose: url and canonical_url (so it isn't crawled again),
    # simhash and simhash_bands (so near-copies are caught as duplicates)
    page.status = "rejected"
    page.status_reason = _status_reason("purged", admin, reason)
    page.purged_at = now
    await session.execute(delete(page_topics).where(page_topics.c.page_id == page.id))
    # The curator's tool results can quote the page; keep only its decisions
    await session.execute(
        update(CuratorReview).where(CuratorReview.page_id == page.id).values(steps=[])
    )
    _record(session, page, admin, "purge", from_status, reason)
    await session.commit()
