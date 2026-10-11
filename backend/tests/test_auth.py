import re

from sqlalchemy import select

from app.models import User
from app.security import verify_password

SIGNUP_RESPONSE = {"message": "Check your email to finish signing up."}
INVALID_LINK = {"detail": "This link is invalid or has expired."}
EMAIL = "bernice@example.com"
PASSWORD = "first-password-123"


def extract_token(email_body: str) -> str:
    match = re.search(r"token=([\w-]+)", email_body)
    assert match is not None, "no verification link in the email"
    return match.group(1)


async def signup(client, email=EMAIL, password=PASSWORD):
    return await client.post(
        "/auth/signup", json={"email": email, "password": password}
    )


async def get_user(session_factory, email=EMAIL) -> User | None:
    async with session_factory() as session:
        return await session.scalar(select(User).where(User.email == email))


async def test_signup_new_email_sends_confirmation(client, email_sender):
    response = await signup(client)

    assert response.status_code == 202
    assert response.json() == SIGNUP_RESPONSE
    assert len(email_sender.sent) == 1
    sent = email_sender.sent[0]
    assert sent.to == EMAIL
    assert sent.subject == "Confirm your email"
    assert extract_token(sent.body)


async def test_signup_normalizes_email(client, email_sender, session_factory):
    response = await signup(client, email="  Bernice@Example.COM  ")

    assert response.status_code == 202
    assert email_sender.sent[0].to == EMAIL
    assert await get_user(session_factory) is not None


async def test_signup_never_stores_plain_password(client, session_factory):
    await signup(client)

    user = await get_user(session_factory)
    assert user is not None
    assert PASSWORD not in user.password_hash
    assert verify_password(user.password_hash, PASSWORD)


async def test_signup_response_same_for_existing_email(client, email_sender):
    first = await signup(client)
    token = extract_token(email_sender.sent[0].body)
    await client.post("/auth/verify-email", json={"token": token})

    second = await signup(client, email="BERNICE@example.com")

    assert first.status_code == second.status_code == 202
    assert first.json() == second.json() == SIGNUP_RESPONSE
    assert len(email_sender.sent) == 2
    assert "already have an account" in email_sender.sent[1].body


async def test_signup_unverified_resends_and_updates_password(
    client, email_sender, session_factory
):
    await signup(client, password="first-password-123")
    await signup(client, password="second-password-456")

    assert len(email_sender.sent) == 2
    assert all(e.subject == "Confirm your email" for e in email_sender.sent)
    user = await get_user(session_factory)
    assert user is not None
    assert verify_password(user.password_hash, "second-password-456")
    assert not verify_password(user.password_hash, "first-password-123")


async def test_verify_email_marks_user_verified(client, email_sender, session_factory):
    await signup(client)
    token = extract_token(email_sender.sent[0].body)

    response = await client.post("/auth/verify-email", json={"token": token})

    assert response.status_code == 200
    assert response.json() == {"message": "Email verified."}
    user = await get_user(session_factory)
    assert user is not None
    assert user.email_verified_at is not None


async def test_verify_token_works_only_once(client, email_sender):
    await signup(client)
    token = extract_token(email_sender.sent[0].body)

    first = await client.post("/auth/verify-email", json={"token": token})
    second = await client.post("/auth/verify-email", json={"token": token})

    assert first.status_code == 200
    assert second.status_code == 400
    assert second.json() == INVALID_LINK


async def test_verify_invalid_token(client):
    response = await client.post("/auth/verify-email", json={"token": "made-up"})

    assert response.status_code == 400
    assert response.json() == INVALID_LINK


async def test_signup_rejects_short_password(client, email_sender):
    response = await signup(client, password="7-chars")

    assert response.status_code == 422
    assert email_sender.sent == []


async def test_signup_rejects_invalid_email(client, email_sender):
    response = await signup(client, email="not-an-email")

    assert response.status_code == 422
    assert email_sender.sent == []
