from fastapi import APIRouter

from app.dependencies import SessionDep
from app.schemas.topics import TopicResponse
from app.services import topics as topics_service

router = APIRouter(prefix="/topics", tags=["topics"])


@router.get("")
async def list_topics(session: SessionDep) -> list[TopicResponse]:
    topics = await topics_service.list_topics(session)
    return [TopicResponse.model_validate(topic) for topic in topics]
