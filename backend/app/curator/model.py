"""The chat model the agent thinks with.

LangChain's ChatOpenAI talks to Gemini, OpenAI, and Ollama alike (all speak
the OpenAI protocol). Each call goes through LLMRouter.run, so the agent gets
the same failover, pacing, daily caps, and 429 cooldowns as enrichment.
"""

from typing import Any, Protocol

import httpx
import openai
from langchain_core.messages import AIMessage, AnyMessage
from langchain_core.runnables import Runnable
from langchain_openai import ChatOpenAI

from app.ai.llm import (
    ChatProvider,
    LLMRouter,
    ProviderError,
    RateLimitedError,
    retry_after_seconds,
)

MODEL_TIMEOUT_SECONDS = 60
ERROR_DETAIL_CHARS = 300


def _reason(error: openai.APIStatusError) -> str:
    """The provider's own explanation, e.g. which part of the request it refused."""
    body = error.body
    if isinstance(body, dict) and isinstance(body.get("message"), str):
        text = body["message"]
    else:
        text = error.message
    return " ".join(text.split())[:ERROR_DETAIL_CHARS]


class AgentModel(Protocol):
    async def invoke(self, messages: list[AnyMessage]) -> tuple[AIMessage, str]:
        """The model's next message, and the name of the provider that wrote it."""
        ...


class RouterAgentModel:
    def __init__(
        self,
        router: LLMRouter,
        http: httpx.AsyncClient,
        tools: list[dict[str, Any]],
    ) -> None:
        self.router = router
        self.http = http
        self.tools = tools
        self._models: dict[str, Runnable] = {}

    def _model(self, provider: ChatProvider) -> Runnable:
        if provider.name not in self._models:
            chat = ChatOpenAI(
                model=provider.model,
                # Ollama ignores the key, but the client insists on one
                api_key=provider.api_key or "not-needed",
                base_url=provider.base_url,
                temperature=0,
                max_retries=0,  # LLMRouter decides what happens after a failure
                timeout=MODEL_TIMEOUT_SECONDS,
                http_async_client=self.http,
                # Use our client exactly as configured (keeps proxy settings)
                http_socket_options=(),
            )
            self._models[provider.name] = chat.bind_tools(self.tools)
        return self._models[provider.name]

    async def invoke(self, messages: list[AnyMessage]) -> tuple[AIMessage, str]:
        async def call(provider: ChatProvider) -> AIMessage:
            try:
                message = await self._model(provider).ainvoke(messages)
            except openai.RateLimitError as error:
                raise RateLimitedError(retry_after_seconds(error.response)) from error
            except openai.APIStatusError as error:
                # Keep the provider's reason (e.g. which part of the request it
                # refused). It never contains the API key.
                raise ProviderError(
                    f"HTTP {error.status_code}: {_reason(error)}"
                ) from error
            except openai.OpenAIError as error:
                raise ProviderError(type(error).__name__) from error
            if not isinstance(message, AIMessage):
                raise ProviderError("unexpected answer type")
            return message

        return await self.router.run(call)
