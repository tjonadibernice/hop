import uuid

from redis.asyncio import Redis

from app.config import settings
from app.security import generate_token, hash_token


def _session_key(token: str) -> str:
    """Redis key for a session. Only the token's hash is stored, never the token."""
    return f"session:{hash_token(token)}"


async def create_session(redis: Redis, user_id: uuid.UUID) -> str:
    token = generate_token()
    await redis.set(_session_key(token), str(user_id), ex=settings.session_ttl_seconds)
    return token


async def get_session_user_id(redis: Redis, token: str) -> uuid.UUID | None:
    user_id = await redis.get(_session_key(token))
    if user_id is None:
        return None
    return uuid.UUID(user_id)


async def delete_session(redis: Redis, token: str) -> None:
    await redis.delete(_session_key(token))
