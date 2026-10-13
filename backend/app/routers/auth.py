from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, Response

from app.config import settings
from app.dependencies import CurrentUserDep, EmailSenderDep, RedisDep, SessionDep
from app.schemas.auth import (
    LoginRequest,
    MessageResponse,
    SignupRequest,
    UserResponse,
    VerifyEmailRequest,
)
from app.services import auth as auth_service
from app.services import sessions

router = APIRouter(prefix="/auth", tags=["auth"])

LOGIN_FAILED = (
    "Incorrect email or password. If you just signed up, confirm your email first."
)


def _set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=settings.session_cookie_name,
        value=token,
        max_age=settings.session_ttl_seconds,
        httponly=True,  # JavaScript can't read it, so XSS can't steal it
        secure=settings.cookie_secure,  # HTTPS only, in production
        samesite="lax",  # not sent on cross-site POSTs, which blocks CSRF
        path="/",
    )


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


@router.post("/login")
async def login(
    body: LoginRequest,
    response: Response,
    session: SessionDep,
    redis: RedisDep,
) -> UserResponse:
    user = await auth_service.authenticate(session, body.email, body.password)
    if user is None:
        raise HTTPException(status_code=401, detail=LOGIN_FAILED)

    token = await sessions.create_session(redis, user.id)
    _set_session_cookie(response, token)
    return UserResponse.model_validate(user)


@router.post("/logout", status_code=204)
async def logout(request: Request, response: Response, redis: RedisDep) -> None:
    token = request.cookies.get(settings.session_cookie_name)
    if token is not None:
        await sessions.delete_session(redis, token)
    response.delete_cookie(
        key=settings.session_cookie_name,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )


@router.get("/me")
async def me(user: CurrentUserDep) -> UserResponse:
    return UserResponse.model_validate(user)
