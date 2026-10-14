import uuid
from typing import Literal

from pydantic import BaseModel

Reaction = Literal["like", "dislike"]


class ReactionRequest(BaseModel):
    reaction: Reaction


class ReactionResponse(BaseModel):
    page_id: uuid.UUID
    reaction: Reaction
