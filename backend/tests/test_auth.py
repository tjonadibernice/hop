import re
import uuid

import pytest
from sqlalchemy import select

from app.models.user import User
from app.security import verify_password


def _extract_token(email_body: str) -> str:
    match = re.search(r"token=([\w-]+)", email_body)
    assert match is not None
    return match.group(1)


def _unique_email(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}@example.com"


@pytest.mark.asyncio
async def test_signup_new_email_sends_confirmation(client, email_sender):
    email = _unique_email("new")
    response = await client.post(
        "/auth/signup",
        json={"email": email, "password": "supersecure123"},
    )

    assert response.status_code == 202
    assert response.json() == {"message": "Check your email to finish signing up."}
    assert len(email_sender.sent) == 1

    sent_email = email_sender.sent[0]
    assert sent_email.to == email
    assert sent_email.subject == "Confirm your email"
    assert "verify-email?token=" in sent_email.body
    assert _extract_token(sent_email.body)


@pytest.mark.asyncio
async def test_signup_response_same_for_existing_email(client, email_sender):
    email = _unique_email("existing")
    payload = {"email": email, "password": "supersecret123"}

    first = await client.post("/auth/signup", json=payload)
    assert first.status_code == 202
    assert first.json() == {"message": "Check your email to finish signing up."}

    token = _extract_token(email_sender.sent[0].body)
    verified = await client.post("/auth/verify-email", json={"token": token})
    assert verified.status_code == 200
    assert verified.json() == {"message": "Email verified."}

    second = await client.post("/auth/signup", json=payload)
    assert second.status_code == 202
    assert second.json() == {"message": "Check your email to finish signing up."}
    assert len(email_sender.sent) == 2
    assert "already have an account" in email_sender.sent[1].body.lower()


@pytest.mark.asyncio
async def test_signup_unverified_resends_and_updates_password(client, email_sender, session_factory):
    email = _unique_email("unverified")
    first_password = "firstpassword123"
    second_password = "secondpassword456"

    first = await client.post("/auth/signup", json={"email": email, "password": first_password})
    assert first.status_code == 202
    assert len(email_sender.sent) == 1

    second = await client.post("/auth/signup", json={"email": email, "password": second_password})
    assert second.status_code == 202
    assert len(email_sender.sent) == 2

    async with session_factory() as session:
        user = await session.scalar(select(User).where(User.email == email))
        assert user is not None
        assert verify_password(user.password_hash, second_password) is True
        assert verify_password(user.password_hash, first_password) is False


@pytest.mark.asyncio
async def test_verify_email_marks_user_verified(client, email_sender, session_factory):
    email = _unique_email("verify")
    response = await client.post(
        "/auth/signup",
        json={"email": email, "password": "somepassword123"},
    )
    assert response.status_code == 202

    token = _extract_token(email_sender.sent[0].body)
    verify_response = await client.post("/auth/verify-email", json={"token": token})
    assert verify_response.status_code == 200
    assert verify_response.json() == {"message": "Email verified."}

    async with session_factory() as session:
        user = await session.scalar(select(User).where(User.email == email))
        assert user is not None
        assert user.email_verified_at is not None


@pytest.mark.asyncio
async def test_verify_token_works_only_once(client, email_sender):
    email = _unique_email("once")
    response = await client.post(
        "/auth/signup",
        json={"email": email, "password": "somepassword123"},
    )
    assert response.status_code == 202

    token = _extract_token(email_sender.sent[0].body)

    first = await client.post("/auth/verify-email", json={"token": token})
    assert first.status_code == 200
    assert first.json() == {"message": "Email verified."}

    second = await client.post("/auth/verify-email", json={"token": token})
    assert second.status_code == 400
    assert second.json() == {"detail": "This link is invalid or has expired."}


@pytest.mark.asyncio
async def test_verify_invalid_token(client):
    response = await client.post("/auth/verify-email", json={"token": "not-a-real-token"})

    assert response.status_code == 400
    assert response.json() == {"detail": "This link is invalid or has expired."}


@pytest.mark.asyncio
async def test_signup_rejects_short_password(client):
    response = await client.post(
        "/auth/signup",
        json={"email": "shortpass@example.com", "password": "short"},
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_signup_rejects_invalid_email(client):
    response = await client.post(
        "/auth/signup",
        json={"email": "not-an-email", "password": "validpassword123"},
    )

    assert response.status_code == 422
