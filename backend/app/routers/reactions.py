import uuid

from fastapi import APIRouter, HTTPException

from app.dependencies import CurrentUserDep, SessionDep
from app.schemas.pages import PageResponse
from app.schemas.reactions import ReactionRequest, ReactionResponse
from app.services import reactions as reactions_service

router = APIRouter(tags=["reactions"])


@router.put("/pages/{page_id}/reaction")
async def set_reaction(
    page_id: uuid.UUID,
    body: ReactionRequest,
    user: CurrentUserDep,
    session: SessionDep,
) -> ReactionResponse:
    try:
        await reactions_service.react(session, user.id, page_id, body.reaction)
    except reactions_service.PageNotViewedError:
        # Same response whether the page doesn't exist or just wasn't shown
        raise HTTPException(status_code=404, detail="Page not found.") from None
    return ReactionResponse(page_id=page_id, reaction=body.reaction)


@router.get("/me/likes")
async def list_likes(user: CurrentUserDep, session: SessionDep) -> list[PageResponse]:
    pages = await reactions_service.liked_pages(session, user.id)
    return [PageResponse.model_validate(page) for page in pages]
