"""Admin-only endpoints for the review screen. Every route needs an admin
(ADMIN_EMAILS); others get 403, logged-out visitors 401."""

import uuid
from typing import Literal

from fastapi import APIRouter, HTTPException, Query

from app.dependencies import AdminUserDep, SessionDep
from app.schemas.admin import (
    AdminPageDetail,
    AdminPageSummary,
    ApproveRequest,
    CuratorReviewResponse,
    PurgeRequest,
    ReasonRequest,
    ReviewActionResponse,
)
from app.services import review as review_service

router = APIRouter(prefix="/admin", tags=["admin"])


def _error(error: review_service.ReviewError) -> HTTPException:
    status = {
        review_service.PageNotFoundError: 404,
        review_service.UnknownTopicError: 400,
        review_service.ActionNotAllowedError: 409,
    }[type(error)]
    return HTTPException(status_code=status, detail=str(error))


async def _summaries(session, pages) -> list[AdminPageSummary]:
    latest = await review_service.latest_reviews(session, [page.id for page in pages])
    return [
        AdminPageSummary.model_validate(page).model_copy(
            update={
                "latest_review": (
                    CuratorReviewResponse.model_validate(latest[page.id])
                    if page.id in latest
                    else None
                )
            }
        )
        for page in pages
    ]


async def _detail(session, page_id: uuid.UUID) -> AdminPageDetail:
    try:
        detail = await review_service.page_detail(session, page_id)
    except review_service.ReviewError as error:
        raise _error(error) from None
    reviews = [CuratorReviewResponse.model_validate(r) for r in detail.reviews]
    summary = AdminPageSummary.model_validate(detail.page)
    return AdminPageDetail(
        **summary.model_dump(exclude={"latest_review"}),
        latest_review=reviews[0] if reviews else None,
        summary=detail.page.summary,
        excerpt=detail.excerpt,
        reviews=reviews,
        actions=[ReviewActionResponse.model_validate(a) for a in detail.actions],
    )


@router.get("/review")
async def review_queue(
    admin: AdminUserDep,
    session: SessionDep,
    show: Literal["escalated", "all"] = "escalated",
    limit: int = Query(default=50, ge=1, le=200),
) -> list[AdminPageSummary]:
    pages = await review_service.review_queue(
        session, escalated_only=show == "escalated", limit=limit
    )
    return await _summaries(session, pages)


@router.get("/pages")
async def search_pages(
    admin: AdminUserDep,
    session: SessionDep,
    q: str = Query(min_length=2, max_length=200),
) -> list[AdminPageSummary]:
    return await _summaries(session, await review_service.search_pages(session, q))


@router.get("/pages/{page_id}")
async def page_detail(
    page_id: uuid.UUID, admin: AdminUserDep, session: SessionDep
) -> AdminPageDetail:
    return await _detail(session, page_id)


@router.post("/pages/{page_id}/approve")
async def approve(
    page_id: uuid.UUID, body: ApproveRequest, admin: AdminUserDep, session: SessionDep
) -> AdminPageDetail:
    try:
        await review_service.approve(session, admin, page_id, body.topics, body.reason)
    except review_service.ReviewError as error:
        raise _error(error) from None
    return await _detail(session, page_id)


@router.post("/pages/{page_id}/reject")
async def reject(
    page_id: uuid.UUID, body: ReasonRequest, admin: AdminUserDep, session: SessionDep
) -> AdminPageDetail:
    try:
        await review_service.reject(session, admin, page_id, body.reason)
    except review_service.ReviewError as error:
        raise _error(error) from None
    return await _detail(session, page_id)


@router.post("/pages/{page_id}/remove")
async def remove(
    page_id: uuid.UUID, body: ReasonRequest, admin: AdminUserDep, session: SessionDep
) -> AdminPageDetail:
    try:
        await review_service.remove(session, admin, page_id, body.reason)
    except review_service.ReviewError as error:
        raise _error(error) from None
    return await _detail(session, page_id)


@router.post("/pages/{page_id}/purge")
async def purge(
    page_id: uuid.UUID, body: PurgeRequest, admin: AdminUserDep, session: SessionDep
) -> AdminPageDetail:
    try:
        await review_service.purge(
            session, admin, page_id, body.reason, body.confirm_url
        )
    except review_service.ReviewError as error:
        raise _error(error) from None
    return await _detail(session, page_id)
