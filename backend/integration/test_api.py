"""End-to-end tests against the real API container.

Nothing is faked: the image runs with real Postgres, Redis, and Mailpit, and
these tests talk to it over HTTP like the frontend does. They need a running
stack, so they're kept out of the normal test run:

    make integration          (locally, with Docker Compose)

CI runs them in the Container job (.github/workflows/ci.yml).
"""

import os
import re
import time
import uuid

import httpx
import pytest

API_URL = os.environ.get("API_URL")
MAILPIT_URL = os.environ.get("MAILPIT_URL", "http://127.0.0.1:8025")
PASSWORD = "integration-password-1"

pytestmark = pytest.mark.skipif(not API_URL, reason="API_URL is not set")


@pytest.fixture
def api():
    with httpx.Client(base_url=API_URL, timeout=10) as client:
        yield client


def new_email() -> str:
    return f"it-{uuid.uuid4().hex[:12]}@example.com"


def confirmation_token(email: str, timeout: float = 15.0) -> str:
    """The token from the confirmation email Mailpit caught for this address."""
    deadline = time.monotonic() + timeout
    with httpx.Client(base_url=MAILPIT_URL, timeout=5) as mailpit:
        while time.monotonic() < deadline:
            found = mailpit.get("/api/v1/search", params={"query": f"to:{email}"})
            messages = found.json().get("messages") or []
            if messages:
                message = mailpit.get(f"/api/v1/message/{messages[0]['ID']}").json()
                match = re.search(r"token=([\w-]+)", message["Text"])
                assert match, "the email has no confirmation link"
                return match.group(1)
            time.sleep(0.3)
    raise AssertionError(f"no confirmation email for {email} within {timeout}s")


def sign_up_and_log_in(api: httpx.Client) -> str:
    email = new_email()
    signup = api.post("/auth/signup", json={"email": email, "password": PASSWORD})
    assert signup.status_code == 202
    verify = api.post("/auth/verify-email", json={"token": confirmation_token(email)})
    assert verify.status_code == 200
    login = api.post("/auth/login", json={"email": email, "password": PASSWORD})
    assert login.status_code == 200
    return email


def test_the_container_is_healthy(api):
    assert api.get("/health/live").json() == {"status": "ok"}
    ready = api.get("/health/ready")
    assert ready.status_code == 200
    assert ready.json()["checks"] == {"postgres": "ok", "redis": "ok"}


def test_a_new_user_can_hop_and_like_a_page(api):
    email = sign_up_and_log_in(api)
    assert api.get("/auth/me").json()["email"] == email

    topics = api.get("/topics").json()
    assert len(topics) == 15
    saved = api.put("/me/interests", json={"topic_ids": [t["id"] for t in topics]})
    assert saved.status_code == 200

    hop = api.post("/hop")
    assert hop.status_code == 200, hop.text  # the seeded starter pages
    page = hop.json()
    liked = api.put(f"/pages/{page['id']}/reaction", json={"reaction": "like"})
    assert liked.status_code == 200
    assert [p["id"] for p in api.get("/me/likes").json()] == [page["id"]]

    assert api.post("/auth/logout").status_code == 204
    assert api.get("/auth/me").status_code == 401


def test_the_session_cookie_is_locked_down(api):
    email = new_email()
    api.post("/auth/signup", json={"email": email, "password": PASSWORD})
    api.post("/auth/verify-email", json={"token": confirmation_token(email)})

    login = api.post("/auth/login", json={"email": email, "password": PASSWORD})

    cookie = login.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie


def test_password_guessing_is_rate_limited(api):
    email = new_email()
    attempts = [
        api.post("/auth/login", json={"email": email, "password": "wrong-guess"})
        for _ in range(6)
    ]

    assert [r.status_code for r in attempts] == [401] * 5 + [429]
    assert int(attempts[-1].headers["retry-after"]) > 0


def test_admin_endpoints_are_closed_to_users(api):
    sign_up_and_log_in(api)

    assert api.get("/admin/review").status_code == 403
