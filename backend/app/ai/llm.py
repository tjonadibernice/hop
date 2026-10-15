"""Structured JSON from chat models, with failover between providers.

Gemini, OpenAI, and Ollama all speak the OpenAI chat completions protocol,
so one small client covers them: only the base URL, key, and model change.

Providers are tried in order. A provider that answers 429 (rate limited) is
put on cooldown in Redis and skipped until its limit resets, so a busy free
tier never makes us wait. Any other failure, including an answer that doesn't
match the schema, moves on to the next provider.
"""

import json
import logging
from dataclasses import dataclass
from typing import Any

import httpx
from pydantic import BaseModel, ValidationError
from redis.asyncio import Redis

from app.config import Settings

logger = logging.getLogger(__name__)

DEFAULT_COOLDOWN_SECONDS = 60
MAX_COOLDOWN_SECONDS = 24 * 60 * 60


@dataclass(frozen=True)
class ChatProvider:
    name: str
    base_url: str  # ends before /chat/completions
    model: str
    api_key: str | None = None


class ProviderError(Exception):
    """One provider failed; the next one may still work."""


class RateLimitedError(ProviderError):
    def __init__(self, retry_after: int) -> None:
        super().__init__(f"rate limited for {retry_after}s")
        self.retry_after = retry_after


class AllProvidersFailedError(Exception):
    """No provider produced a valid answer. Worth retrying later."""


def _retry_after(response: httpx.Response) -> int:
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
        raise RateLimitedError(_retry_after(response))
    if response.status_code >= 400:
        raise ProviderError(f"HTTP {response.status_code}")
    try:
        content = response.json()["choices"][0]["message"]["content"]
        return json.loads(_strip_code_fence(content))
    except (KeyError, IndexError, TypeError, ValueError) as error:
        raise ProviderError("unreadable answer") from error


class LLMRouter:
    def __init__(
        self, client: httpx.AsyncClient, redis: Redis, providers: list[ChatProvider]
    ) -> None:
        self.client = client
        self.redis = redis
        self.providers = providers

    @staticmethod
    def _cooldown_key(provider: ChatProvider) -> str:
        return f"llm:cooldown:{provider.name}"

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
        failures = []
        for provider in self.providers:
            if await self.redis.exists(self._cooldown_key(provider)):
                failures.append(f"{provider.name}: cooling down")
                continue
            try:
                data = await complete_json(
                    self.client,
                    provider,
                    system=system,
                    user=user,
                    schema_name=schema_name,
                    schema=schema,
                )
                return response_model.model_validate(data), provider.name
            except RateLimitedError as error:
                await self.redis.set(
                    self._cooldown_key(provider), "1", ex=error.retry_after
                )
                failures.append(f"{provider.name}: {error}")
            except ProviderError as error:
                failures.append(f"{provider.name}: {error}")
            except ValidationError:
                failures.append(f"{provider.name}: answer didn't match the schema")
            logger.warning("LLM provider failed: %s", failures[-1])
        raise AllProvidersFailedError("; ".join(failures) or "no providers configured")


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
            )
        )
    if settings.openai_api_key:
        providers.append(
            ChatProvider(
                "openai",
                "https://api.openai.com/v1",
                settings.openai_model,
                settings.openai_api_key,
            )
        )
    if settings.ollama_base_url:
        providers.append(
            ChatProvider("ollama", settings.ollama_base_url, settings.ollama_model)
        )
    return providers
