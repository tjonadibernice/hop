import fakeredis
import pytest
from httpx import ASGITransport, AsyncClient

from app.dependencies import get_email_sender, get_redis
from app.email import Email
from app.main import app


class FakeEmailSender:
    def __init__(self) -> None:
        self.sent: list[Email] = []

    async def send(self, email: Email) -> None:
        self.sent.append(email)


@pytest.fixture
def email_sender() -> FakeEmailSender:
    return FakeEmailSender()


@pytest.fixture
def redis() -> fakeredis.FakeAsyncRedis:
    return fakeredis.FakeAsyncRedis(decode_responses=True)


@pytest.fixture
def session_factory(client):
    return app.state.session_factory


@pytest.fixture
async def client(email_sender: FakeEmailSender, redis: fakeredis.FakeAsyncRedis):
    app.dependency_overrides[get_email_sender] = lambda: email_sender
    app.dependency_overrides[get_redis] = lambda: redis

    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as test_client:
            yield test_client

    app.dependency_overrides.clear()