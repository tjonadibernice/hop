"""The chat model the agent thinks with.

LangChain's ChatOpenAI talks to Gemini, OpenAI, and Ollama alike (all speak
the OpenAI protocol). Each call goes through LLMRouter.run, so the agent gets
the same failover, pacing, daily caps, and 429 cooldowns as enrichment.
"""

from typing import Any, Protocol

import httpx
import openai
from langchain_core.language_models import LanguageModelInput
from langchain_core.messages import AIMessage, AnyMessage
from langchain_core.outputs import ChatResult
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


EXTRA_CONTENT_KEY = "tool_call_extra_content"


class ToolCallExtrasChatOpenAI(ChatOpenAI):
    """ChatOpenAI that keeps each tool call's `extra_content` across turns.

    Gemini's thinking models attach a "thought signature" to every tool call
    (tool_calls[i].extra_content.google.thought_signature) and refuse the
    next request (HTTP 400) unless it comes back unchanged with the history.
    ChatOpenAI drops fields it doesn't know, so this subclass stores them on
    the AIMessage when the answer arrives and puts them back on the matching
    tool call when the history is sent again.
    """

    def _create_chat_result(
        self, response: Any, generation_info: dict | None = None
    ) -> ChatResult:
        result = super()._create_chat_result(response, generation_info)
        data = response if isinstance(response, dict) else response.model_dump()
        for generation, choice in zip(
            result.generations, data.get("choices") or [], strict=False
        ):
            calls = (choice.get("message") or {}).get("tool_calls") or []
            extras = {
                call["id"]: call["extra_content"]
                for call in calls
                if call.get("id") and call.get("extra_content")
            }
            if extras:
                generation.message.additional_kwargs[EXTRA_CONTENT_KEY] = extras
        return result

    def _get_request_payload(
        self,
        input_: LanguageModelInput,
        *,
        stop: list[str] | None = None,
        **kwargs: Any,
    ) -> dict:
        payload = super()._get_request_payload(input_, stop=stop, **kwargs)
        extras: dict[str, Any] = {}
        for message in self._convert_input(input_).to_messages():
            if isinstance(message, AIMessage):
                extras.update(message.additional_kwargs.get(EXTRA_CONTENT_KEY, {}))
        for message in payload.get("messages", []):
            message.pop(EXTRA_CONTENT_KEY, None)
            for call in message.get("tool_calls") or []:
                if call.get("id") in extras:
                    call["extra_content"] = extras[call["id"]]
        return payload


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
            # Only Gemini sends (and needs back) extra_content on tool calls
            model_class = (
                ToolCallExtrasChatOpenAI if provider.name == "gemini" else ChatOpenAI
            )
            chat = model_class(
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
