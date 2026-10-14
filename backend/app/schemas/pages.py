import uuid

from pydantic import BaseModel, ConfigDict

from app.schemas.topics import TopicResponse


class PageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    url: str
    title: str
    summary: str | None
    embeddable: bool | None
    topics: list[TopicResponse]
