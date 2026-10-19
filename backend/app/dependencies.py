from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.email import EmailSender
from app.models import User
from app.services import sessions
from app.services.hop_queue import Refiller


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    async with request.app.state.session_factory() as session:
        yield session


def get_email_sender(request: Request) -> EmailSender:
    return request.app.state.email_sender


def get_redis(request: Request) -> Redis:
    return request.app.state.redis


def get_refiller(request: Request) -> Refiller:
    return request.app.state.refiller


SessionDep = Annotated[AsyncSession, Depends(get_session)]
RedisDep = Annotated[Redis, Depends(get_redis)]
EmailSenderDep = Annotated[EmailSender, Depends(get_email_sender)]
RefillerDep = Annotated[Refiller, Depends(get_refiller)]


async def get_current_user(
    request: Request, session: SessionDep, redis: RedisDep
) -> User:
    """The logged-in user, based on the session cookie. Responds 401 otherwise."""
    not_authenticated = HTTPException(status_code=401, detail="Not authenticated.")

    token = request.cookies.get(settings.session_cookie_name)
    if token is None:
        raise not_authenticated

    user_id = await sessions.get_session_user_id(redis, token)
    if user_id is None:
        raise not_authenticated

    user = await session.get(User, user_id)
    if user is None:
        raise not_authenticated

    return user


CurrentUserDep = Annotated[User, Depends(get_current_user)]


async def get_admin_user(user: CurrentUserDep) -> User:
    """The logged-in user, if their email is in ADMIN_EMAILS. Responds 403 otherwise."""
    if not settings.is_admin(user.email):
        raise HTTPException(status_code=403, detail="Admins only.")
    return user


AdminUserDep = Annotated[User, Depends(get_admin_user)]
