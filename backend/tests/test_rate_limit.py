import re

import pytest
from httpx import ASGITransport, AsyncClient

from app.config import settings
from app.main import app
from app.routers import auth as auth_router
from app.services import rate_limit
from app.services.rate_limit import Rule

RULE = Rule("test", limit=3, window_seconds=60)
START = 6000.0  # the start of a window (6000 / 60 = 100)


# --- The counter -------------------------------------------------------------------


async def test_allows_up_to_the_limit_then_refuses(redis):
    verdicts = [await rate_limit.hit(redis, RULE, "s", now=START + i) for i in range(4)]

    assert [v.allowed for v in verdicts] == [True, True, True, False]
    assert 0 < verdicts[-1].retry_after <= 60


async def test_the_window_slides(redis):
    for _ in range(3):
        await rate_limit.hit(redis, RULE, "s", now=START + 50)

    # 10 s into the next window, 5/6 of the old count still applies: 2.5 + 1
    assert not (await rate_limit.peek(redis, RULE, "s", now=START + 70)).allowed
    # Halfway through, 1.5 + 1 fits
    assert (await rate_limit.peek(redis, RULE, "s", now=START + 90)).allowed
    # Two windows later the old count is gone
    assert (await rate_limit.hit(redis, RULE, "s", now=START + 125)).allowed


async def test_a_full_window_waits_for_the_next_one(redis):
    for _ in range(3):
        await rate_limit.hit(redis, RULE, "s", now=START + 10)

    verdict = await rate_limit.peek(redis, RULE, "s", now=START + 10)

    assert (verdict.allowed, verdict.retry_after) == (False, 50)


async def test_refused_events_are_counted_too(redis):
    for i in range(6):
        await rate_limit.hit(redis, RULE, "s", now=START + i)

    # Six counted: even a fully weighted-down previous window needs time
    assert not (await rate_limit.hit(redis, RULE, "s", now=START + 61)).allowed


async def test_peek_counts_nothing_and_reset_forgets(redis):
    for _ in range(5):
        assert (await rate_limit.peek(redis, RULE, "s", now=START)).allowed
    for _ in range(3):
        await rate_limit.hit(redis, RULE, "s", now=START)
    assert not (await rate_limit.peek(redis, RULE, "s", now=START)).allowed

    await rate_limit.reset(redis, RULE, "s", now=START)

    assert (await rate_limit.peek(redis, RULE, "s", now=START)).allowed


async def test_keys_never_hold_a_readable_email(redis):
    await rate_limit.hit(redis, RULE, rate_limit.subject_of("Bernice@Example.com "))

    [key] = await redis.keys("rl:*")
    assert "bernice" not in key.lower()
    # Same email, different case and spaces: same subject
    assert rate_limit.subject_of("bernice@example.com") in key


# --- Login ---------------------------------------------------------------------------

PASSWORD = "first-password-123"
EMAIL = "bernice@example.com"  # logged_in_client's account


async def login(client, password=PASSWORD, email=EMAIL):
    return await client.post("/auth/login", json={"email": email, "password": password})


async def test_password_guessing_is_stopped(logged_in_client):
    for _ in range(5):
        assert (await login(logged_in_client, "wrong-guess")).status_code == 401

    blocked = await login(logged_in_client)  # even the right password

    assert blocked.status_code == 429
    assert blocked.json()["detail"].startswith("Too many attempts. Please try again in")
    assert 0 < int(blocked.headers["retry-after"]) <= 15 * 60


async def test_other_accounts_are_not_affected(logged_in_client):
    for _ in range(5):
        await login(logged_in_client, "wrong-guess")

    other = await login(logged_in_client, "x", email="someone@example.com")

    assert other.status_code == 401


async def test_a_successful_login_forgets_earlier_failures(logged_in_client):
    for _ in range(4):
        await login(logged_in_client, "typo")
    assert (await login(logged_in_client)).status_code == 200

    for _ in range(4):
        assert (await login(logged_in_client, "typo")).status_code == 401
    assert (await login(logged_in_client)).status_code == 200


def client_from(ip: str) -> AsyncClient:
    transport = ASGITransport(app=app, client=(ip, 51000))
    return AsyncClient(transport=transport, base_url="http://test")


async def test_guessing_from_many_addresses_is_slowed(logged_in_client):
    for n in range(4):  # 4 addresses x 5 guesses = 20, the per-email limit
        async with client_from(f"203.0.113.{n}") as attacker:
            for _ in range(5):
                assert (await login(attacker, "guess")).status_code == 401

    async with client_from("203.0.113.99") as attacker:
        assert (await login(attacker, "guess")).status_code == 429


async def test_one_address_has_a_login_limit(client):
    statuses = [
        (await login(client, "x", email=f"u{i}@example.com")).status_code
        for i in range(31)
    ]

    assert statuses[:30] == [401] * 30
    assert statuses[30] == 429


# --- Sign-up and confirmation --------------------------------------------------------


async def signup(client, email):
    return await client.post(
        "/auth/signup", json={"email": email, "password": "a-good-password"}
    )


async def test_one_inbox_gets_at_most_three_signup_emails_an_hour(client, email_sender):
    statuses = [
        (await signup(client, "victim@example.com")).status_code for _ in range(4)
    ]

    assert statuses == [202, 202, 202, 429]
    assert len(email_sender.sent) == 3


async def test_the_limit_reveals_nothing_about_accounts(logged_in_client):
    # A registered email and a new one are limited the same way
    registered = [(await signup(logged_in_client, EMAIL)).status_code for _ in range(3)]
    new = [
        (await signup(logged_in_client, "new@example.com")).status_code
        for _ in range(4)
    ]

    assert registered == [202, 202, 429]  # the fixture's own sign-up counted once
    assert new == [202, 202, 202, 429]


async def test_one_address_has_a_signup_limit(client):
    statuses = [
        (await signup(client, f"u{i}@example.com")).status_code for i in range(11)
    ]

    assert statuses == [202] * 10 + [429]


async def test_confirmation_attempts_are_limited(client):
    statuses = [
        (await client.post("/auth/verify-email", json={"token": f"t{i}"})).status_code
        for i in range(31)
    ]

    assert statuses == [400] * 30 + [429]


async def test_limits_can_be_turned_off(client, monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_enabled", False)

    statuses = [
        (await signup(client, "same@example.com")).status_code for _ in range(5)
    ]

    assert statuses == [202] * 5


@pytest.mark.parametrize(("seconds", "words"), [(30, "1 minute"), (600, "10 minutes")])
def test_the_message_says_how_long_to_wait(seconds, words):
    error = auth_router._too_many(rate_limit.Verdict(False, seconds))

    assert re.search(rf"in {words}\.$", error.detail)
    assert error.headers == {"Retry-After": str(seconds)}
