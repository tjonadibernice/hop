from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.security import hash_password


class EmailAlreadyRegisteredError(Exception):
    pass


async def create_user(session: AsyncSession, email: str, password: str) -> User:
    user = User(
        email=email.strip().lower(),
        password_hash=hash_password(password),
    )
    session.add(user)

    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise EmailAlreadyRegisteredError from exc

    return user