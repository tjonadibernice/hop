import hashlib
import secrets
import uuid
from datetime import UTC, datetime

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.email import Email
from app.models.user import User
from app.security import hash_password


async def create_verification_token(redis: Redis, user_id: uuid.UUID | str) -> str:
    token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    key = f"email_verify:{token_hash}"
    await redis.set(key, str(user_id), ex=86_400)
    return token


def _confirm_email_body(token: str | None = None) -> str:
    if token:
        return (
            "Welcome to Hop! Confirm your email by opening this link within 24 hours:\n\n"
            f"{settings.app_base_url}/verify-email?token={token}\n\n"
            "If you didn't sign up, you can ignore this email."
        )

    return (
        "Welcome to Hop! A confirmation email is on the way for your account. "
        "Please use the most recent link we sent you within 24 hours. If you didn't sign up, "
        "you can ignore this email."
    )


def _already_registered_email_body() -> str:
    return (
        "Someone tried to create a Hop account with this email. You already have an account, "
        "so you can log in instead. If this wasn't you, you can ignore this email."
    )


async def start_signup(session: AsyncSession, redis: Redis, email: str, password: str) -> Email:
    normalized_email = email.strip().lower()
    password_hash = hash_password(password)

    user = await session.scalar(select(User).where(User.email == normalized_email))

    if user is None:
        user = User(email=normalized_email, password_hash=password_hash)
        session.add(user)

        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            user = await session.scalar(select(User).where(User.email == normalized_email))
            # Another signup won the race before our insert committed. Treat this as the
            # existing-unverified-user case rather than failing, so the action remains
            # safe and idempotent for the user who is already in the system.
            if user is None:
                return Email(
                    to=normalized_email,
                    subject="Confirm your email",
                    body=_confirm_email_body(),
                )

        if user is not None and user.email_verified_at is None:
            token = await create_verification_token(redis, user.id)
            return Email(
                to=normalized_email,
                subject="Confirm your email",
                body=_confirm_email_body(token),
            )

        if user is not None and user.email_verified_at is not None:
            return Email(
                to=normalized_email,
                subject="Account already exists",
                body=_already_registered_email_body(),
            )

    if user.email_verified_at is None:
        user.password_hash = password_hash
        await session.commit()
        token = await create_verification_token(redis, user.id)
        return Email(
            to=normalized_email,
            subject="Confirm your email",
            body=_confirm_email_body(token),
        )

    return Email(
        to=normalized_email,
        subject="Account already exists",
        body=_already_registered_email_body(),
    )


async def verify_email(session: AsyncSession, redis: Redis, token: str) -> bool:
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    key = f"email_verify:{token_hash}"
    user_id = await redis.getdel(key)

    if user_id is None:
        return False

    user_id_str = user_id.decode() if isinstance(user_id, bytes) else str(user_id)
    user = await session.get(User, uuid.UUID(user_id_str))
    if user is None:
        return False

    if user.email_verified_at is None:
        user.email_verified_at = datetime.now(UTC)
        await session.commit()

    return True
