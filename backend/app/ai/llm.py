"""Structured JSON from chat models, with failover between providers.

Gemini, OpenAI, and Ollama all speak the OpenAI chat completions protocol,
so one small client covers them: only the base URL, key, and model change.

Providers are tried in order. A provider that answers 429 (rate limited) is
put on cooldown in Redis and skipped until its limit resets, so a busy free
tier never makes us wait. Any other failure, including an answer that doesn't
match the schema, moves on to the next provider.

Two optional limits per provider keep us inside its quota and our budget:
- requests_per_minute spaces calls evenly (one every 60/N seconds, shared
  by all workers through Redis), so bursts don't trigger 429s at all.
- max_calls_per_day caps paid usage; past it, the provider is skipped
  until midnight UTC.
"""

import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from pydantic import BaseModel, ValidationError
from redis.asyncio import Redis

from app.config import Settings
from app.ingestion.politeness import wait_for_slot

logger = logging.getLogger(__name__)

DEFAULT_COOLDOWN_SECONDS = 60
MAX_COOLDOWN_SECONDS = 24 * 60 * 60


@dataclass(frozen=True)
class ChatProvider:
    name: str
    base_url: str  # ends before /chat/completions
    model: str
    api_key: str | None = None
    requests_per_minute: int | None = None
    max_calls_per_day: int | None = None


class ProviderError(Exception):
    """One provider failed; the next one may still work."""


class RateLimitedError(ProviderError):
    def __init__(self, retry_after: int) -> None:
        super().__init__(f"rate limited for {retry_after}s")
        self.retry_after = retry_after


class AllProvidersFailedError(Exception):
    """No provider produced a valid answer. Worth retrying later.

    retry_after is set when every provider was only waiting (cooldown or daily
    cap): the number of seconds until the first one is available again.
    """

    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


def retry_after_seconds(response: httpx.Response) -> int:
    try:
        seconds = int(response.headers.get("retry-after", ""))
    except ValueError:
        return DEFAULT_COOLDOWN_SECONDS
    return max(1, min(seconds, MAX_COOLDOWN_SECONDS))


def _strip_code_fence(text: str) -> str:
    """Some models wrap JSON in ```json ... ``` even when asked not to."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else ""
        text = text.rsplit("```", 1)[0]
    return text.strip()


async def complete_json(
    client: httpx.AsyncClient,
    provider: ChatProvider,
    *,
    system: str,
    user: str,
    schema_name: str,
    schema: dict[str, Any],
) -> Any:
    """One chat completion constrained to a JSON schema; returns the parsed JSON."""
    headers = (
        {"Authorization": f"Bearer {provider.api_key}"} if provider.api_key else {}
    )
    body = {
        "model": provider.model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": schema_name, "strict": True, "schema": schema},
        },
        "temperature": 0,
    }
    url = provider.base_url.rstrip("/") + "/chat/completions"
    try:
        response = await client.post(url, json=body, headers=headers)
    except httpx.HTTPError as error:
        raise ProviderError(f"{type(error).__name__}") from error

    if response.status_code == 429:
        raise RateLimitedError(retry_after_seconds(response))
    if response.status_code >= 400:
        raise ProviderError(f"HTTP {response.status_code}")
    try:
        content = response.json()["choices"][0]["message"]["content"]
        return json.loads(_strip_code_fence(content))
    except (KeyError, IndexError, TypeError, ValueError) as error:
        raise ProviderError("unreadable answer") from error


class LLMRouter:
    def __init__(
        self,
        client: httpx.AsyncClient,
        redis: Redis,
        providers: list[ChatProvider],
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.client = client
        self.redis = redis
        self.providers = providers
        self.now = now

    @staticmethod
    def _cooldown_key(provider: ChatProvider) -> str:
        return f"llm:cooldown:{provider.name}"

    def _calls_key(self, provider: ChatProvider) -> str:
        return f"llm:calls:{provider.name}:{self.now().date().isoformat()}"

    def _seconds_until_midnight(self) -> float:
        now = self.now()
        midnight = (now + timedelta(days=1)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        return (midnight - now).total_seconds()

    async def _wait_needed(self, provider: ChatProvider) -> tuple[str, float] | None:
        """Why the provider can't be used right now, and for how many seconds."""
        cooldown = await self.redis.ttl(self._cooldown_key(provider))
        if cooldown > 0:
            return "cooling down", float(cooldown)
        if provider.max_calls_per_day is not None:
            calls = int(await self.redis.get(self._calls_key(provider)) or 0)
            if calls >= provider.max_calls_per_day:
                return (
                    f"daily limit reached ({calls} calls)",
                    self._seconds_until_midnight(),
                )
        return None

    async def _count_call(self, provider: ChatProvider) -> None:
        if provider.max_calls_per_day is not None:
            key = self._calls_key(provider)
            await self.redis.incr(key)
            await self.redis.expire(key, 2 * 24 * 60 * 60)

    async def run[R](
        self, call: Callable[[ChatProvider], Awaitable[R]]
    ) -> tuple[R, str]:
        """Run `call` with the first provider that works; return its result and name.

        Every caller gets the same rules: pacing, the daily cap, and cooldowns
        after a 429. `call` raises RateLimitedError or ProviderError to move on
        to the next provider. Used for structured JSON (generate) and by the
        curator agent's tool-calling model.
        """
        failures: list[str] = []
        waits: list[float] = []  # seconds until each waiting provider is free
        hard_failure = False
        for provider in self.providers:
            wait = await self._wait_needed(provider)
            if wait is not None:
                reason, seconds = wait
                failures.append(f"{provider.name}: {reason}")
                waits.append(seconds)
                continue
            if provider.requests_per_minute:
                await wait_for_slot(
                    self.redis,
                    f"llm:next:{provider.name}",
                    60 / provider.requests_per_minute,
                )
            await self._count_call(provider)
            try:
                return await call(provider), provider.name
            except RateLimitedError as error:
                await self.redis.set(
                    self._cooldown_key(provider), "1", ex=error.retry_after
                )
                failures.append(f"{provider.name}: {error}")
                waits.append(float(error.retry_after))
            except ProviderError as error:
                failures.append(f"{provider.name}: {error}")
                hard_failure = True
            logger.warning("LLM provider failed: %s", failures[-1])

        retry_after = min(waits) if waits and not hard_failure else None
        raise AllProvidersFailedError(
            "; ".join(failures) or "no providers configured", retry_after
        )

    async def generate[T: BaseModel](
        self,
        *,
        system: str,
        user: str,
        schema_name: str,
        schema: dict[str, Any],
        response_model: type[T],
    ) -> tuple[T, str]:
        """The first valid answer, and the name of the provider that gave it."""

        async def call(provider: ChatProvider) -> T:
            data = await complete_json(
                self.client,
                provider,
                system=system,
                user=user,
                schema_name=schema_name,
                schema=schema,
            )
            try:
                return response_model.model_validate(data)
            except ValidationError as error:
                raise ProviderError("answer didn't match the schema") from error

        return await self.run(call)


def providers_from_settings(settings: Settings) -> list[ChatProvider]:
    """The configured providers, in failover order."""
    providers = []
    if settings.gemini_api_key:
        providers.append(
            ChatProvider(
                "gemini",
                "https://generativelanguage.googleapis.com/v1beta/openai",
                settings.gemini_model,
                settings.gemini_api_key,
                settings.gemini_requests_per_minute,
                settings.gemini_max_calls_per_day,
            )
        )
    if settings.openai_api_key:
        providers.append(
            ChatProvider(
                "openai",
                "https://api.openai.com/v1",
                settings.openai_model,
                settings.openai_api_key,
                settings.openai_requests_per_minute,
                settings.openai_max_calls_per_day,
            )
        )
    if settings.ollama_base_url:
        providers.append(
            ChatProvider("ollama", settings.ollama_base_url, settings.ollama_model)
        )
    return providers
