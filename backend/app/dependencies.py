from collections.abc import AsyncIterator

from fastapi import Request
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.email import EmailSender


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    async with request.app.state.session_factory() as session:
        yield session


def get_email_sender(request: Request) -> EmailSender:
    return request.app.state.email_sender


def get_redis(request: Request) -> Redis:
    return request.app.state.redis
