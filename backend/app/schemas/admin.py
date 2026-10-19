import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.topics import TopicResponse

Reason = Field(min_length=1, max_length=300)


class CuratorStep(BaseModel):
    tool: str
    args: dict[str, Any] = {}
    result: str = ""


class CuratorReviewResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    proposed: str
    outcome: str
    reason: str
    blocked_by: str | None
    topics: list[str]
    quality: float | None
    provider: str | None
    steps: list[CuratorStep]
    created_at: datetime


class ReviewActionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    actor_email: str
    action: str
    from_status: str
    to_status: str
    reason: str | None
    topics: list[str]
    created_at: datetime


class AdminPageSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    url: str
    site: str | None
    title: str
    status: str
    status_reason: str | None
    quality_score: float | None
    topics: list[TopicResponse]
    created_at: datetime
    curated_at: datetime | None
    purged_at: datetime | None
    # The curator's latest review, if it has looked at the page
    latest_review: CuratorReviewResponse | None = None


class AdminPageDetail(AdminPageSummary):
    summary: str | None
    excerpt: str | None  # the first part of the stored text
    reviews: list[CuratorReviewResponse]  # newest first
    actions: list[ReviewActionResponse]  # newest first


class ApproveRequest(BaseModel):
    topics: list[str] = Field(min_length=1, max_length=3)
    reason: str | None = Field(default=None, max_length=300)


class ReasonRequest(BaseModel):
    reason: str = Reason


class PurgeRequest(BaseModel):
    reason: str = Reason
    # The page's exact URL, typed by the admin: a purge can't be undone
    confirm_url: str = Field(min_length=1, max_length=2048)
