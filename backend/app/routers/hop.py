from fastapi import APIRouter, HTTPException

from app.dependencies import CurrentUserDep, SessionDep
from app.schemas.pages import PageResponse
from app.services import hop as hop_service

router = APIRouter(tags=["hop"])


# POST, not GET: each hop records a view, and GET requests must not change
# anything (browsers and link previewers may send them on their own)
@router.post("/hop")
async def hop(user: CurrentUserDep, session: SessionDep) -> PageResponse:
    try:
        page = await hop_service.next_page(session, user.id)
    except hop_service.NoInterestsError:
        raise HTTPException(
            status_code=409, detail="Choose at least 3 interests first."
        ) from None

    if page is None:
        raise HTTPException(
            status_code=404,
            detail="You've seen every page in your interests. "
            "Add more interests or check back later.",
        )
    return PageResponse.model_validate(page)
