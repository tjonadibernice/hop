import uuid
from datetime import UTC, datetime

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.email import Email
from app.models import User
from app.security import (
    DUMMY_PASSWORD_HASH,
    generate_token,
    hash_password,
    hash_token,
    password_needs_rehash,
    verify_password,
)

VERIFICATION_TOKEN_TTL_SECONDS = 24 * 60 * 60


def _verification_key(token: str) -> str:
    """Redis key for a token. Only the token's hash is stored, never the token."""
    return f"email_verify:{hash_token(token)}"


async def create_verification_token(redis: Redis, user_id: uuid.UUID) -> str:
    token = generate_token()
    await redis.set(
        _verification_key(token), str(user_id), ex=VERIFICATION_TOKEN_TTL_SECONDS
    )
    return token


def _confirmation_email(to: str, token: str) -> Email:
    link = f"{settings.app_base_url}/verify-email?token={token}"
    return Email(
        to=to,
        subject="Confirm your email",
        body=(
            "Welcome to Hop! Confirm your email by opening this link "
            "within 24 hours:\n\n"
            f"{link}\n\n"
            "If you didn't sign up, you can ignore this email."
        ),
    )


def _already_registered_email(to: str) -> Email:
    return Email(
        to=to,
        subject="You already have a Hop account",
        body=(
            "Someone tried to create a Hop account with this email. "
            "You already have an account, so you can log in instead.\n\n"
            "If this wasn't you, you can ignore this email."
        ),
    )


def _normalize_email(email: str) -> str:
    return email.strip().lower()


async def _get_user_by_email(session: AsyncSession, email: str) -> User | None:
    return await session.scalar(select(User).where(User.email == email))


async def _create_user(session: AsyncSession, email: str, password_hash: str) -> User:
    user = User(email=email, password_hash=password_hash)
    session.add(user)
    try:
        await session.commit()
    except IntegrityError:
        # Another sign-up with the same email committed between our lookup and
        # our insert. Use the account that won the race instead of failing.
        await session.rollback()
        existing = await _get_user_by_email(session, email)
        if existing is None:
            raise
        return existing
    return user


async def start_signup(
    session: AsyncSession, redis: Redis, email: str, password: str
) -> Email:
    """Handle a sign-up and return the email to send.

    The caller always responds the same way, so only the inbox owner
    learns whether the email already had an account.
    """
    email = _normalize_email(email)
    # Hash first, in every case, so response time doesn't reveal which case ran
    password_hash = hash_password(password)

    user = await _get_user_by_email(session, email)
    if user is None:
        user = await _create_user(session, email, password_hash)
    elif user.email_verified_at is None:
        # Unverified accounts belong to whoever can read the inbox,
        # so the latest sign-up sets the password
        user.password_hash = password_hash
        await session.commit()

    if user.email_verified_at is not None:
        return _already_registered_email(email)

    token = await create_verification_token(redis, user.id)
    return _confirmation_email(email, token)


async def verify_email(session: AsyncSession, redis: Redis, token: str) -> bool:
    # GETDEL reads and deletes in one step, so each token works only once
    user_id = await redis.getdel(_verification_key(token))
    if user_id is None:
        return False

    user = await session.get(User, uuid.UUID(user_id))
    if user is None:
        return False

    if user.email_verified_at is None:
        user.email_verified_at = datetime.now(UTC)
        await session.commit()
    return True


async def authenticate(session: AsyncSession, email: str, password: str) -> User | None:
    """Return the user if the email and password match a verified account.

    Every failure returns None, so the caller can't tell an unknown email,
    a wrong password, and an unverified account apart.
    """
    user = await _get_user_by_email(session, _normalize_email(email))

    if user is None:
        # Do the same slow work as a real check, so timing doesn't reveal
        # whether the email has an account
        verify_password(DUMMY_PASSWORD_HASH, password)
        return None

    if not verify_password(user.password_hash, password):
        return None

    if user.email_verified_at is None:
        return None

    if password_needs_rehash(user.password_hash):
        # Upgrade old hashes while we have the plain password
        user.password_hash = hash_password(password)
        await session.commit()

    return user
