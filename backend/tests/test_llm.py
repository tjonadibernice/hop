import json

import httpx
import pytest
from pydantic import BaseModel

from app.ai.llm import (
    AllProvidersFailedError,
    ChatProvider,
    LLMRouter,
    providers_from_settings,
)
from app.config import Settings

GEMINI = ChatProvider("gemini", "https://gemini.test/v1", "flash-lite", "g-key")
OPENAI = ChatProvider("openai", "https://openai.test/v1", "luna", "o-key")
OLLAMA = ChatProvider("ollama", "http://ollama.test/v1", "llama3.2")


class Answer(BaseModel):
    word: str


def chat_response(content: str) -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})


class FakeProviders:
    """Answers per host; records every request."""

    def __init__(self, answers: dict[str, httpx.Response]) -> None:
        self.answers = answers
        self.requests: list[httpx.Request] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self.answers[request.url.host]

    def hosts(self) -> list[str]:
        return [request.url.host for request in self.requests]


def router(fake: FakeProviders, redis, providers) -> LLMRouter:
    client = httpx.AsyncClient(transport=httpx.MockTransport(fake.handler))
    return LLMRouter(client, redis, providers)


async def ask(llm: LLMRouter):
    return await llm.generate(
        system="Answer with one word.",
        user="Say hi",
        schema_name="answer",
        schema={"type": "object", "properties": {"word": {"type": "string"}}},
        response_model=Answer,
    )


async def test_first_provider_answers(redis):
    fake = FakeProviders({"gemini.test": chat_response('{"word": "hi"}')})

    answer, provider = await ask(router(fake, redis, [GEMINI, OPENAI]))

    assert (answer.word, provider) == ("hi", "gemini")
    request = fake.requests[0]
    assert request.url.path == "/v1/chat/completions"
    assert request.headers["authorization"] == "Bearer g-key"
    body = json.loads(request.content)
    assert body["model"] == "flash-lite"
    assert body["response_format"]["type"] == "json_schema"
    assert body["response_format"]["json_schema"]["strict"] is True


async def test_rate_limited_provider_fails_over_and_cools_down(redis):
    fake = FakeProviders(
        {
            "gemini.test": httpx.Response(429, headers={"retry-after": "120"}),
            "openai.test": chat_response('{"word": "hello"}'),
        }
    )
    llm = router(fake, redis, [GEMINI, OPENAI])

    first = await ask(llm)
    second = await ask(llm)

    assert first[1] == second[1] == "openai"
    # Gemini was asked once, then skipped while cooling down
    assert fake.hosts() == ["gemini.test", "openai.test", "openai.test"]
    assert 100 < await redis.ttl("llm:cooldown:gemini") <= 120


@pytest.mark.parametrize(
    "bad",
    [
        httpx.Response(500),
        httpx.Response(401),
        chat_response("not json at all"),
        chat_response('{"wrong_field": 1}'),
        httpx.Response(200, json={"unexpected": "shape"}),
    ],
)
async def test_any_failure_moves_to_the_next_provider(redis, bad):
    fake = FakeProviders(
        {"gemini.test": bad, "ollama.test": chat_response('{"word": "ok"}')}
    )

    answer, provider = await ask(router(fake, redis, [GEMINI, OLLAMA]))

    assert (answer.word, provider) == ("ok", "ollama")
    assert "authorization" not in fake.requests[-1].headers  # Ollama needs no key


async def test_code_fences_are_tolerated(redis):
    fake = FakeProviders({"gemini.test": chat_response('```json\n{"word": "hi"}\n```')})

    answer, _ = await ask(router(fake, redis, [GEMINI]))

    assert answer.word == "hi"


async def test_all_providers_failing_raises(redis):
    fake = FakeProviders(
        {"gemini.test": httpx.Response(503), "openai.test": httpx.Response(429)}
    )

    with pytest.raises(AllProvidersFailedError, match="gemini.*openai"):
        await ask(router(fake, redis, [GEMINI, OPENAI]))


async def test_no_providers_configured_raises(redis):
    with pytest.raises(AllProvidersFailedError, match="no providers"):
        await ask(router(FakeProviders({}), redis, []))


def test_providers_follow_the_failover_order():
    settings = Settings(
        database_url="postgresql+asyncpg://x",
        redis_url="redis://x",
        gemini_api_key="g",
        openai_api_key="",
        ollama_base_url="http://localhost:11434/v1",
    )
    assert [p.name for p in providers_from_settings(settings)] == ["gemini", "ollama"]
