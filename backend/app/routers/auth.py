from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_email_sender, get_redis, get_session
from app.email import EmailSender
from app.schemas.auth import MessageResponse, SignupRequest, VerifyEmailRequest
from app.services import auth as auth_service

router = APIRouter(prefix="/auth", tags=["auth"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
RedisDep = Annotated[Redis, Depends(get_redis)]
EmailSenderDep = Annotated[EmailSender, Depends(get_email_sender)]


@router.post("/signup", status_code=202)
async def signup(
    body: SignupRequest,
    background_tasks: BackgroundTasks,
    session: SessionDep,
    redis: RedisDep,
    email_sender: EmailSenderDep,
) -> MessageResponse:
    email = await auth_service.start_signup(session, redis, body.email, body.password)
    # Sent after the response, so slow email delivery can't reveal anything
    background_tasks.add_task(email_sender.send, email)
    return MessageResponse(message="Check your email to finish signing up.")


@router.post("/verify-email")
async def verify_email(
    body: VerifyEmailRequest,
    session: SessionDep,
    redis: RedisDep,
) -> MessageResponse:
    if not await auth_service.verify_email(session, redis, body.token):
        raise HTTPException(
            status_code=400, detail="This link is invalid or has expired."
        )
    return MessageResponse(message="Email verified.")
