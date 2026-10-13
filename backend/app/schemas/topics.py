from pydantic import BaseModel, ConfigDict, Field, field_validator


class TopicResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    slug: str
    name: str


class InterestsUpdate(BaseModel):
    topic_ids: list[int] = Field(min_length=3, max_length=15)

    @field_validator("topic_ids")
    @classmethod
    def no_duplicates(cls, topic_ids: list[int]) -> list[int]:
        if len(set(topic_ids)) != len(topic_ids):
            raise ValueError("topic_ids must not contain duplicates")
        return topic_ids


class InterestsResponse(BaseModel):
    topics: list[TopicResponse]
