import re

from app.config import settings

EMAIL = "bernice@example.com"
PASSWORD = "first-password-123"
LOGIN_FAILED = {
    "detail": (
        "Incorrect email or password. If you just signed up, confirm your email first."
    )
}


async def sign_up(client, email_sender, email=EMAIL, password=PASSWORD) -> str:
    """Sign up and return the verification token from the email."""
    await client.post("/auth/signup", json={"email": email, "password": password})
    match = re.search(r"token=([\w-]+)", email_sender.sent[-1].body)
    assert match is not None
    return match.group(1)


async def create_verified_user(client, email_sender, email=EMAIL, password=PASSWORD):
    token = await sign_up(client, email_sender, email, password)
    response = await client.post("/auth/verify-email", json={"token": token})
    assert response.status_code == 200


async def log_in(client, email=EMAIL, password=PASSWORD):
    return await client.post("/auth/login", json={"email": email, "password": password})


async def test_login_returns_user_and_sets_session_cookie(client, email_sender):
    await create_verified_user(client, email_sender)

    response = await log_in(client)

    assert response.status_code == 200
    assert response.json()["email"] == EMAIL
    assert "password_hash" not in response.json()
    cookie = response.headers["set-cookie"]
    assert cookie.startswith(f"{settings.session_cookie_name}=")
    assert "HttpOnly" in cookie
    assert "samesite=lax" in cookie.lower()


async def test_login_is_case_insensitive_for_email(client, email_sender):
    await create_verified_user(client, email_sender)

    response = await log_in(client, email="BERNICE@Example.com")

    assert response.status_code == 200


async def test_me_returns_logged_in_user(client, email_sender):
    await create_verified_user(client, email_sender)
    await log_in(client)

    response = await client.get("/auth/me")

    assert response.status_code == 200
    assert response.json()["email"] == EMAIL


async def test_me_without_session_returns_401(client):
    response = await client.get("/auth/me")

    assert response.status_code == 401


async def test_me_with_made_up_session_returns_401(client):
    client.cookies.set(settings.session_cookie_name, "made-up-token")

    response = await client.get("/auth/me")

    assert response.status_code == 401


async def test_login_failures_all_look_the_same(client, email_sender):
    await create_verified_user(client, email_sender)
    await sign_up(client, email_sender, email="unverified@example.com")

    wrong_password = await log_in(client, password="wrong-password")
    unknown_email = await log_in(client, email="nobody@example.com")
    unverified = await log_in(client, email="unverified@example.com")

    for response in (wrong_password, unknown_email, unverified):
        assert response.status_code == 401
        assert response.json() == LOGIN_FAILED
        assert "set-cookie" not in response.headers


async def test_logout_ends_the_session(client, email_sender):
    await create_verified_user(client, email_sender)
    await log_in(client)
    token = client.cookies.get(settings.session_cookie_name)

    response = await client.post("/auth/logout")

    assert response.status_code == 204
    assert (await client.get("/auth/me")).status_code == 401
    # Even if someone kept a copy of the old token, it no longer works
    client.cookies.set(settings.session_cookie_name, token)
    assert (await client.get("/auth/me")).status_code == 401


async def test_logout_without_session_is_harmless(client):
    response = await client.post("/auth/logout")

    assert response.status_code == 204


async def test_session_token_is_stored_hashed(client, email_sender, redis):
    await create_verified_user(client, email_sender)
    await log_in(client)
    token = client.cookies.get(settings.session_cookie_name)

    keys = await redis.keys("session:*")

    assert len(keys) == 1
    assert token not in keys[0]
    assert await redis.ttl(keys[0]) > 0
