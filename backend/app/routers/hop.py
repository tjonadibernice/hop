import logging

from fastapi import APIRouter, HTTPException, Response

from app.config import settings
from app.dependencies import CurrentUserDep, RedisDep, RefillerDep, SessionDep
from app.schemas.pages import HopResponse, PageResponse
from app.services import hop as hop_service
from app.services import hop_queue

logger = logging.getLogger(__name__)

router = APIRouter(tags=["hop"])


# POST, not GET: each hop records a view, and GET requests must not change
# anything (browsers and link previewers may send them on their own)
@router.post("/hop")
async def hop(
    user: CurrentUserDep,
    session: SessionDep,
    redis: RedisDep,
    refiller: RefillerDep,
    response: Response,
) -> HopResponse:
    queue = redis if settings.hop_queue_enabled else None
    try:
        result = await hop_service.next_page(session, user.id, redis=queue)
    except hop_service.NoInterestsError:
        raise HTTPException(
            status_code=409, detail="Choose at least 3 interests first."
        ) from None

    if result is None:
        raise HTTPException(
            status_code=404,
            detail="You've seen every page in your interests. "
            "Add more interests or check back later.",
        )

    # Running low? Ask the worker to pick more pages in the background, so
    # the user's next hops are fast again
    if queue is not None and await hop_queue.claim_refill(redis, user.id):
        try:
            await refiller(user.id)
        except Exception:
            # The hop itself worked; the next one will just be picked live
            logger.exception("couldn't queue a refill for %s", user.id)
            await hop_queue.release_refill(redis, user.id)

    # "queue" or "live": handy for debugging and used by the load test
    response.headers["X-Hop-Source"] = result.source
    return HopResponse(
        **PageResponse.model_validate(result.page).model_dump(),
        strategy=result.strategy,
    )
