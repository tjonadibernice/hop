import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.orm import undefer

from app.config import settings
from app.models import (
    EMBEDDING_DIMENSIONS,
    CuratorReview,
    Interaction,
    Page,
    ReviewAction,
    page_topics,
)

ADMIN = "bernice@example.com"  # the logged_in_client's email


@pytest.fixture
def admin_client(logged_in_client, monkeypatch):
    monkeypatch.setattr(settings, "admin_emails", f"someone@else.test, {ADMIN.upper()}")
    return logged_in_client


async def make_page(
    session_factory, *, status="needs_review", curated=True, title=None, url=None
) -> Page:
    url = url or f"https://example.org/{uuid.uuid4().hex}"
    async with session_factory() as session:
        page = Page(
            url=url,
            canonical_url=url,
            site="example.org",
            title=title or "A page about focus",
            summary="A summary.",
            content="Some text from the page. " * 200,
            status=status,
            status_reason="borderline quality (0.55)",
            quality_score=0.55,
            simhash=12345,
            simhash_bands=[1, 2, 3],
            embedding=[0.1] * EMBEDDING_DIMENSIONS,
            curated_at=datetime.now(UTC) if curated else None,
        )
        session.add(page)
        await session.commit()
        return page


async def add_review(session_factory, page, **values) -> None:
    async with session_factory() as session:
        session.add(
            CuratorReview(
                page_id=page.id,
                proposed=values.get("proposed", "approve"),
                outcome="needs_review",
                reason="curator: Good, but no Safe Browsing check.",
                blocked_by=values.get("blocked_by", "no Safe Browsing check"),
                topics=["productivity-focus"],
                quality=0.8,
                provider="gemini",
                steps=[
                    {
                        "tool": "fetch_live_page",
                        "args": {},
                        "result": "HTTP 200; <page_content>Some text</page_content>",
                    }
                ],
            )
        )
        await session.commit()


async def load(session_factory, page_id) -> Page:
    async with session_factory() as session:
        return await session.get(
            Page,
            page_id,
            options=[
                undefer(Page.content),
                undefer(Page.embedding),
                undefer(Page.outlinks),
            ],
        )


async def actions(session_factory, page_id) -> list[ReviewAction]:
    async with session_factory() as session:
        return list(
            await session.scalars(
                select(ReviewAction)
                .where(ReviewAction.page_id == page_id)
                .order_by(ReviewAction.id)
            )
        )


# --- Who can use it ----------------------------------------------------------------


async def test_admin_endpoints_need_a_login(client):
    assert (await client.get("/admin/review")).status_code == 401


async def test_admin_endpoints_need_an_admin(logged_in_client, monkeypatch):
    monkeypatch.setattr(settings, "admin_emails", "someone@else.test")

    response = await logged_in_client.get("/admin/review")

    assert response.status_code == 403
    assert (await logged_in_client.get("/auth/me")).json()["is_admin"] is False


async def test_me_says_who_is_an_admin(admin_client):
    assert (await admin_client.get("/auth/me")).json()["is_admin"] is True


# --- The queue and search --------------------------------------------------------


async def test_queue_shows_pages_the_curator_handed_over(admin_client, session_factory):
    escalated = await make_page(session_factory)
    await add_review(session_factory, escalated)
    waiting = await make_page(session_factory, curated=False)
    await make_page(session_factory, status="approved")

    queue = (await admin_client.get("/admin/review")).json()

    assert [item["id"] for item in queue] == [str(escalated.id)]
    review = queue[0]["latest_review"]
    assert (review["proposed"], review["blocked_by"]) == (
        "approve",
        "no Safe Browsing check",
    )
    assert review["steps"][0]["tool"] == "fetch_live_page"

    everything = (await admin_client.get("/admin/review?show=all")).json()
    assert {item["id"] for item in everything} == {str(escalated.id), str(waiting.id)}


async def test_search_finds_any_page_by_url_or_title(admin_client, session_factory):
    page = await make_page(session_factory, status="approved", title="100% focus")
    await make_page(session_factory, status="approved", title="1000 focus")

    by_title = (await admin_client.get("/admin/pages", params={"q": "100%"})).json()
    by_url = (await admin_client.get("/admin/pages", params={"q": page.url})).json()

    # "%" is matched literally, not as a wildcard
    assert [item["id"] for item in by_title] == [str(page.id)]
    assert [item["id"] for item in by_url] == [str(page.id)]


async def test_page_detail_has_the_whole_story(admin_client, session_factory):
    page = await make_page(session_factory)
    await add_review(session_factory, page)

    detail = (await admin_client.get(f"/admin/pages/{page.id}")).json()

    assert detail["excerpt"].startswith("Some text from the page.")
    assert len(detail["excerpt"]) == 1500
    assert len(detail["reviews"]) == 1
    assert detail["actions"] == []
    assert (await admin_client.get(f"/admin/pages/{uuid.uuid4()}")).status_code == 404


# --- Decisions ---------------------------------------------------------------------


async def test_approve_puts_the_page_live_with_chosen_topics(
    admin_client, session_factory
):
    page = await make_page(session_factory)

    response = await admin_client.post(
        f"/admin/pages/{page.id}/approve",
        json={"topics": ["productivity-focus", "habits-routines"], "reason": "Solid."},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "approved"
    assert {t["slug"] for t in body["topics"]} == {
        "productivity-focus",
        "habits-routines",
    }
    assert body["status_reason"] == f"approved by {ADMIN}: Solid."
    assert body["actions"][0]["actor_email"] == ADMIN
    saved = await load(session_factory, page.id)
    assert saved.next_check_at is not None


@pytest.mark.parametrize(
    ("topics", "status"),
    [([], 422), (["made-up"], 400), (["a", "b", "c", "d"], 422)],
)
async def test_approve_needs_known_topics(
    admin_client, session_factory, topics, status
):
    page = await make_page(session_factory)

    response = await admin_client.post(
        f"/admin/pages/{page.id}/approve", json={"topics": topics}
    )

    assert response.status_code == status
    assert (await load(session_factory, page.id)).status == "needs_review"


async def test_a_rejected_page_can_be_approved_but_not_an_approved_one(
    admin_client, session_factory
):
    rejected = await make_page(session_factory, status="rejected")
    approved = await make_page(session_factory, status="approved")
    body = {"topics": ["productivity-focus"]}

    assert (
        await admin_client.post(f"/admin/pages/{rejected.id}/approve", json=body)
    ).status_code == 200
    response = await admin_client.post(f"/admin/pages/{approved.id}/approve", json=body)
    assert response.status_code == 409


async def test_reject_is_only_for_pages_waiting_for_review(
    admin_client, session_factory
):
    waiting = await make_page(session_factory)
    approved = await make_page(session_factory, status="approved")

    ok = await admin_client.post(
        f"/admin/pages/{waiting.id}/reject", json={"reason": "Thin."}
    )
    refused = await admin_client.post(
        f"/admin/pages/{approved.id}/reject", json={"reason": "Thin."}
    )
    missing_reason = await admin_client.post(
        f"/admin/pages/{waiting.id}/reject", json={"reason": ""}
    )

    assert ok.json()["status"] == "rejected"
    assert refused.status_code == 409
    assert "Remove from Hop" in refused.json()["detail"]
    assert missing_reason.status_code == 422


async def test_remove_takes_a_live_page_out_of_hop_and_likes(
    admin_client, session_factory
):
    page = await make_page(session_factory, status="approved")
    me = (await admin_client.get("/auth/me")).json()["id"]
    async with session_factory() as session:
        for kind in ("view", "like"):
            session.add(Interaction(user_id=me, page_id=page.id, kind=kind))
        await session.commit()
    assert len((await admin_client.get("/me/likes")).json()) == 1

    response = await admin_client.post(
        f"/admin/pages/{page.id}/remove", json={"reason": "Now a parked domain."}
    )

    assert response.json()["status"] == "rejected"
    assert response.json()["status_reason"].startswith(f"removed by {ADMIN}")
    assert (await admin_client.get("/me/likes")).json() == []
    [action] = await actions(session_factory, page.id)
    assert (action.action, action.from_status, action.to_status) == (
        "remove",
        "approved",
        "rejected",
    )
    # History stays: the like is still recorded
    async with session_factory() as session:
        kinds = set(
            await session.scalars(
                select(Interaction.kind).where(Interaction.page_id == page.id)
            )
        )
    assert kinds == {"view", "like"}
    again = await admin_client.post(
        f"/admin/pages/{page.id}/remove", json={"reason": "x"}
    )
    assert again.status_code == 409


# --- Purge ---------------------------------------------------------------------------


async def test_purge_needs_the_exact_url(admin_client, session_factory):
    page = await make_page(session_factory, status="approved")

    response = await admin_client.post(
        f"/admin/pages/{page.id}/purge",
        json={"reason": "Takedown request.", "confirm_url": "https://example.org/x"},
    )

    assert response.status_code == 409
    saved = await load(session_factory, page.id)
    assert (saved.status, saved.purged_at) == ("approved", None)


async def test_purge_erases_the_content_but_keeps_a_tombstone(
    admin_client, session_factory
):
    page = await make_page(session_factory, status="approved", title="Leaked memo")
    await add_review(session_factory, page)
    async with session_factory() as session:
        await session.execute(page_topics.insert().values(page_id=page.id, topic_id=1))
        await session.commit()

    response = await admin_client.post(
        f"/admin/pages/{page.id}/purge",
        json={"reason": "Takedown request.", "confirm_url": page.url},
    )

    assert response.status_code == 200
    saved = await load(session_factory, page.id)
    assert (saved.title, saved.status) == ("[purged]", "rejected")
    assert saved.content is None and saved.summary is None
    assert saved.embedding is None and saved.outlinks is None
    assert saved.purged_at is not None
    # Kept, so the page and near-copies of it can't be crawled back in
    assert (saved.url, saved.canonical_url) == (page.url, page.url)
    assert (saved.simhash, saved.simhash_bands) == (12345, [1, 2, 3])

    detail = response.json()
    assert detail["topics"] == [] and detail["excerpt"] is None
    assert detail["reviews"][0]["steps"] == []  # the curator's quotes are gone
    assert detail["reviews"][0]["reason"]  # its decision stays
    assert detail["actions"][0]["action"] == "purge"

    # Nothing more can be done with it
    for path, body in [
        ("approve", {"topics": ["productivity-focus"]}),
        ("remove", {"reason": "x"}),
    ]:
        refused = await admin_client.post(f"/admin/pages/{page.id}/{path}", json=body)
        assert refused.status_code == 409
