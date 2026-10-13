from fastapi import APIRouter, HTTPException

from app.dependencies import CurrentUserDep, SessionDep
from app.schemas.topics import InterestsResponse, InterestsUpdate, TopicResponse
from app.services import topics as topics_service

router = APIRouter(prefix="/me/interests", tags=["interests"])


def _response(topics) -> InterestsResponse:
    return InterestsResponse(
        topics=[TopicResponse.model_validate(topic) for topic in topics]
    )


@router.get("")
async def get_interests(user: CurrentUserDep, session: SessionDep) -> InterestsResponse:
    return _response(await topics_service.get_interests(session, user.id))


@router.put("")
async def set_interests(
    body: InterestsUpdate, user: CurrentUserDep, session: SessionDep
) -> InterestsResponse:
    try:
        topics = await topics_service.set_interests(session, user.id, body.topic_ids)
    except topics_service.UnknownTopicError:
        raise HTTPException(status_code=400, detail="Unknown topic.") from None
    return _response(topics)
