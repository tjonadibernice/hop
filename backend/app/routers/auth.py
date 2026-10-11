from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_email_sender, get_redis, get_session
from app.email import EmailSender
from app.schemas.auth import MessageResponse, SignupRequest, UserResponse, VerifyEmailRequest
from app.services.auth import start_signup, verify_email as verify_email_token

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/signup", status_code=202, response_model=MessageResponse)
async def signup(
	body: SignupRequest,
	background_tasks: BackgroundTasks,
	session: Annotated[AsyncSession, Depends(get_session)],
	redis: Annotated[Redis, Depends(get_redis)],
	email_sender: Annotated[EmailSender, Depends(get_email_sender)],
) -> MessageResponse:
	email = await start_signup(session, redis, body.email, body.password)
	background_tasks.add_task(email_sender.send, email)
	return {"message": "Check your email to finish signing up."}


@router.post("/verify-email", response_model=MessageResponse)
async def verify_email(
	body: VerifyEmailRequest,
	session: Annotated[AsyncSession, Depends(get_session)],
	redis: Annotated[Redis, Depends(get_redis)],
) -> MessageResponse:
	if await verify_email_token(session, redis, body.token):
		return {"message": "Email verified."}

	raise HTTPException(
		status_code=400,
		detail="This link is invalid or has expired.",
	)
