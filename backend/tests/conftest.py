from collections.abc import AsyncIterator
from pathlib import Path

import fakeredis
import pytest
from alembic import command
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings
from app.dependencies import get_email_sender, get_redis, get_session
from app.email import Email
from app.main import app

ALEMBIC_INI = Path(__file__).resolve().parents[1] / "alembic.ini"


class FakeEmailSender:
    """Collects emails instead of sending them, so tests can read them."""

    def __init__(self) -> None:
        self.sent: list[Email] = []

    async def send(self, email: Email) -> None:
        self.sent.append(email)


@pytest.fixture(scope="session", autouse=True)
def migrated_test_database() -> str:
    """Apply all migrations to the test database once per test run."""
    if settings.test_database_url is None:
        pytest.exit("TEST_DATABASE_URL is not set", returncode=1)

    config = Config(str(ALEMBIC_INI))
    config.attributes["database_url"] = settings.test_database_url
    command.upgrade(config, "head")
    return settings.test_database_url


@pytest.fixture
async def session_factory(
    migrated_test_database: str,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(migrated_test_database)
    yield async_sessionmaker(engine, expire_on_commit=False)

    # Empty the users table after each test so tests don't affect each other
    async with engine.begin() as conn:
        await conn.execute(text("TRUNCATE users CASCADE"))
    await engine.dispose()


@pytest.fixture
def email_sender() -> FakeEmailSender:
    return FakeEmailSender()


@pytest.fixture
def redis() -> fakeredis.FakeAsyncRedis:
    return fakeredis.FakeAsyncRedis(decode_responses=True)


@pytest.fixture
async def client(
    session_factory: async_sessionmaker[AsyncSession],
    email_sender: FakeEmailSender,
    redis: fakeredis.FakeAsyncRedis,
) -> AsyncIterator[AsyncClient]:
    async def override_get_session() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session
    app.dependency_overrides[get_email_sender] = lambda: email_sender
    app.dependency_overrides[get_redis] = lambda: redis

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client

    app.dependency_overrides.clear()
