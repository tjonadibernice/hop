import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.schemas.topics import TopicResponse


class PageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    url: str
    title: str
    summary: str | None
    # "interactive" (a tool, simulation, game, ...) or "article"
    kind: str
    embeddable: bool | None
    topics: list[TopicResponse]


class HopResponse(PageResponse):
    # How the page was picked: by the recommender, or at random (the A/B
    # baseline). The frontend shows "Picked for you" or "Random find".
    strategy: Literal["recommender", "random"]
