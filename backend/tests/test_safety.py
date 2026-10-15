import json

import httpx
import pytest

from app.ingestion.safety import (
    SafetyChecker,
    SafetyCheckError,
    is_blocked,
    load_blocklist,
)

BLOCKLIST = frozenset({"spam.example", "bad.test"})


def checker(handler=None, api_key="sb-key") -> SafetyChecker:
    handler = handler or (lambda request: httpx.Response(200, json={}))
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return SafetyChecker(client, api_key=api_key, blocklist=BLOCKLIST)


@pytest.mark.parametrize(
    ("host", "blocked"),
    [
        ("spam.example", True),
        ("www.spam.example", True),
        ("a.b.bad.test", True),
        ("notspam.example", False),
        ("spam.example.com", False),
    ],
)
def test_blocklist_covers_subdomains(host, blocked):
    assert is_blocked(host, BLOCKLIST) is blocked


def test_shipped_blocklist_loads():
    assert isinstance(load_blocklist(), frozenset)


async def test_blocked_domain_is_unsafe_without_calling_google():
    def handler(request):
        raise AssertionError("Safe Browsing should not be called")

    result = await checker(handler).check("https://www.spam.example/page")

    assert (result.safe, result.reason) == (False, "blocked domain")


async def test_clean_url_is_safe():
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={})  # no matches

    result = await checker(handler).check("https://blog.test/post")

    assert (result.safe, result.checked) == (True, True)
    request = requests[0]
    assert request.method == "POST"
    assert request.url.path == "/v4/threatMatches:find"
    body = json.loads(request.content)
    assert body["threatInfo"]["threatEntries"] == [{"url": "https://blog.test/post"}]
    assert "MALWARE" in body["threatInfo"]["threatTypes"]
    assert request.headers["x-goog-api-key"] == "sb-key"
    assert "sb-key" not in str(request.url)  # never in the URL (logs)


async def test_threats_make_a_url_unsafe():
    def handler(request):
        return httpx.Response(
            200,
            json={
                "matches": [
                    {
                        "threatType": "SOCIAL_ENGINEERING",
                        "threat": {"url": "https://evil.test/"},
                    },
                    {"threatType": "MALWARE", "threat": {"url": "https://evil.test/"}},
                ]
            },
        )

    result = await checker(handler).check("https://evil.test/")

    assert result.safe is False
    assert result.reason == "Safe Browsing: MALWARE, SOCIAL_ENGINEERING"


async def test_without_a_key_the_url_is_unchecked():
    result = await checker(api_key=None).check("https://blog.test/post")

    assert (result.safe, result.checked) == (True, False)


async def test_api_errors_are_retryable():
    with pytest.raises(SafetyCheckError):
        await checker(lambda request: httpx.Response(503)).check("https://blog.test/")


async def test_non_json_answer_is_retryable_not_a_crash():
    def protobuf(request):
        return httpx.Response(200, content=b"\x0a\x05binary")

    with pytest.raises(SafetyCheckError, match="unreadable"):
        await checker(protobuf).check("https://blog.test/")
