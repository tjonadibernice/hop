from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, Response
from redis.asyncio import Redis

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
from app.services import rate_limit, sessions
from app.services.rate_limit import Rule, Verdict

router = APIRouter(prefix="/auth", tags=["auth"])

LOGIN_FAILED = (
    "Incorrect email or password. If you just signed up, confirm your email first."
)

# Rate limits. None of them depends on whether an email is registered, so a
# 429 reveals nothing about accounts.
LOGIN_PER_IP = Rule("login-ip", limit=30, window_seconds=15 * 60)
# Failed logins for one email from one address: stops password guessing
LOGIN_FAILURES = Rule("login-fail", limit=5, window_seconds=15 * 60)
# Failed logins for one email from anywhere: slows guessing spread over many
# addresses. Set high, because anyone can use it to lock an account out
LOGIN_FAILURES_PER_EMAIL = Rule("login-fail-email", limit=20, window_seconds=60 * 60)
SIGNUP_PER_IP = Rule("signup-ip", limit=10, window_seconds=60 * 60)
# Each sign-up sends an email, so this stops flooding someone's inbox
SIGNUP_PER_EMAIL = Rule("signup-email", limit=3, window_seconds=60 * 60)
VERIFY_PER_IP = Rule("verify-ip", limit=30, window_seconds=15 * 60)


def client_ip(request: Request) -> str:
    # Behind a reverse proxy, run uvicorn with --proxy-headers and
    # --forwarded-allow-ips set to the proxy, so this is the real client
    return request.client.host if request.client else "unknown"


def _too_many(verdict: Verdict) -> HTTPException:
    minutes = max(1, round(verdict.retry_after / 60))
    unit = "minute" if minutes == 1 else "minutes"
    return HTTPException(
        status_code=429,
        detail=f"Too many attempts. Please try again in {minutes} {unit}.",
        headers={"Retry-After": str(verdict.retry_after)},
    )


async def _enforce(redis: Redis, *checks: tuple[Rule, str], count: bool = True) -> None:
    """Count (or with count=False, only check) each rule; 429 if any is over."""
    if not settings.rate_limit_enabled:
        return
    for rule, subject in checks:
        verdict = await (rate_limit.hit if count else rate_limit.peek)(
            redis, rule, subject
        )
        if not verdict.allowed:
            raise _too_many(verdict)


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
    request: Request,
) -> MessageResponse:
    await _enforce(
        redis,
        (SIGNUP_PER_IP, rate_limit.subject_of(client_ip(request))),
        (SIGNUP_PER_EMAIL, rate_limit.subject_of(body.email)),
    )
    email = await auth_service.start_signup(session, redis, body.email, body.password)
    # Sent after the response, so slow email delivery can't reveal anything
    background_tasks.add_task(email_sender.send, email)
    return MessageResponse(message="Check your email to finish signing up.")


@router.post("/verify-email")
async def verify_email(
    body: VerifyEmailRequest,
    session: SessionDep,
    redis: RedisDep,
    request: Request,
) -> MessageResponse:
    await _enforce(redis, (VERIFY_PER_IP, rate_limit.subject_of(client_ip(request))))
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
    request: Request,
) -> UserResponse:
    ip = client_ip(request)
    failures = (
        (LOGIN_FAILURES, rate_limit.subject_of(body.email, ip)),
        (LOGIN_FAILURES_PER_EMAIL, rate_limit.subject_of(body.email)),
    )
    await _enforce(redis, (LOGIN_PER_IP, rate_limit.subject_of(ip)))
    # Checked before the password, so a guesser over the limit learns nothing,
    # not even when the guess is right
    await _enforce(redis, *failures, count=False)

    user = await auth_service.authenticate(session, body.email, body.password)
    if user is None:
        if settings.rate_limit_enabled:
            for rule, subject in failures:
                await rate_limit.hit(redis, rule, subject)
        raise HTTPException(status_code=401, detail=LOGIN_FAILED)
    if settings.rate_limit_enabled:
        # The owner got in: forget their failed attempts from this address
        await rate_limit.reset(redis, *failures[0])

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
