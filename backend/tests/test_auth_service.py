import hashlib
import uuid

import pytest
from fakeredis.aioredis import FakeRedis

from app.models.user import User
from app.services.auth import create_verification_token, start_signup, verify_email


class FakeSession:
    def __init__(self, user: User | None = None):
        self.user = user
        self.committed = False
        self.rolled_back = False

    def add(self, user: User) -> None:
        if user.id is None:
            user.id = uuid.uuid4()
        self.user = user

    async def scalar(self, *_args, **_kwargs):
        return self.user

    async def get(self, model, key):
        if self.user is None:
            return None
        if self.user.id == key:
            return self.user
        return None

    async def commit(self):
        self.committed = True

    async def rollback(self):
        self.rolled_back = True


@pytest.mark.asyncio
async def test_create_verification_token_stores_user_id() -> None:
    redis = FakeRedis()
    user_id = uuid.uuid4()

    token = await create_verification_token(redis, user_id)

    key = f"email_verify:{hashlib.sha256(token.encode()).hexdigest()}"
    stored = await redis.getdel(key)
    assert stored.decode() == str(user_id)


@pytest.mark.asyncio
async def test_start_signup_and_verify_email_round_trip() -> None:
    session = FakeSession()
    redis = FakeRedis()

    email = await start_signup(session, redis, "  User@Example.com  ", "secret-password")

    assert email.to == "user@example.com"
    assert "Confirm your email" in email.subject
    assert "verify-email?token=" in email.body
    assert session.user is not None
    assert session.user.id is not None

    token = email.body.split("token=")[-1].split("\n")[0]
    assert await verify_email(session, redis, token) is True
    assert session.user.email_verified_at is not None
