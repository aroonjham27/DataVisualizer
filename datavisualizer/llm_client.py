from __future__ import annotations

import json
import os
import urllib.request
from dataclasses import dataclass, field
from typing import Any

from .errors import QueryExecutionFailure, RequestValidationError


@dataclass(frozen=True)
class LlmToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class LlmAssistantMessage:
    content: str
    tool_calls: tuple[LlmToolCall, ...] = ()


@dataclass(frozen=True)
class LlmResponse:
    message: LlmAssistantMessage


@dataclass(frozen=True)
class ProviderConfig:
    provider_name: str
    base_url: str
    api_key: str
    model: str
    timeout_seconds: int = 30
    default_max_iterations: int = 4
    referer: str | None = None
    title: str | None = None

    @classmethod
    def from_env(cls) -> "ProviderConfig":
        provider_name = os.getenv("LLM_PROVIDER", "openai_compatible")
        base_url = os.getenv("LLM_BASE_URL") or os.getenv("OPENROUTER_BASE_URL") or "https://openrouter.ai/api/v1"
        api_key = os.getenv("LLM_API_KEY") or os.getenv("OPENROUTER_API_KEY")
        model = os.getenv("LLM_MODEL") or os.getenv("OPENROUTER_MODEL") or os.getenv("ANTHROPIC_MODEL")
        timeout_value = os.getenv("TIMEOUT_SECONDS", "30")
        iterations_value = os.getenv("MAX_ITERATIONS", "4")
        if not api_key:
            raise RequestValidationError("Live LLM API key is not configured in the environment.")
        if not model:
            raise RequestValidationError("Live LLM model is not configured in the environment.")
        try:
            timeout_seconds = int(timeout_value)
            default_max_iterations = int(iterations_value)
        except ValueError as exc:
            raise RequestValidationError("TIMEOUT_SECONDS and MAX_ITERATIONS must be integers.") from exc
        return cls(
            provider_name=provider_name,
            base_url=base_url.rstrip("/"),
            api_key=api_key,
            model=model,
            timeout_seconds=timeout_seconds,
            default_max_iterations=default_max_iterations,
            referer=os.getenv("OPENROUTER_REFERER"),
            title=os.getenv("OPENROUTER_TITLE"),
        )


class LlmClient:
    def generate(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | dict[str, Any] | None = None,
    ) -> LlmResponse:
        raise NotImplementedError


class DisabledLlmClient(LlmClient):
    def __init__(self, reason: str):
        self.reason = reason

    def generate(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | dict[str, Any] | None = None,
    ) -> LlmResponse:
        raise RequestValidationError(self.reason)


class FakeLlmClient(LlmClient):
    def __init__(self, responses: list[LlmResponse]):
        self._responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def generate(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | dict[str, Any] | None = None,
    ) -> LlmResponse:
        self.calls.append(
            {
                "messages": messages,
                "tools": tools or [],
                "tool_choice": tool_choice,
            }
        )
        if not self._responses:
            raise AssertionError("FakeLlmClient has no remaining scripted responses.")
        return self._responses.pop(0)


class OpenAiCompatibleLlmClient(LlmClient):
    def __init__(self, config: ProviderConfig):
        self.config = config

    @classmethod
    def from_env(cls) -> "OpenAiCompatibleLlmClient":
        return cls(ProviderConfig.from_env())

    def generate(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | dict[str, Any] | None = None,
    ) -> LlmResponse:
        body: dict[str, Any] = {
            "model": self.config.model,
            "messages": messages,
        }
        if tools:
            body["tools"] = tools
        if tool_choice is not None:
            body["tool_choice"] = tool_choice

        endpoint = self.config.base_url
        if not endpoint.endswith("/chat/completions"):
            endpoint = f"{endpoint}/chat/completions"
        request = urllib.request.Request(
            endpoint,
            data=json.dumps(body).encode("utf-8"),
            headers=self._headers(),
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.config.timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except Exception as exc:  # noqa: BLE001
            raise QueryExecutionFailure(f"Live LLM request failed: {exc}") from exc
        return self._parse_response(payload)

    def _headers(self) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
        }
        if self.config.referer:
            headers["HTTP-Referer"] = self.config.referer
        if self.config.title:
            headers["X-Title"] = self.config.title
        return headers

    def _parse_response(self, payload: dict[str, Any]) -> LlmResponse:
        try:
            message = payload["choices"][0]["message"]
        except (KeyError, IndexError, TypeError) as exc:
            raise QueryExecutionFailure("Live LLM response did not contain a valid choice message.") from exc
        content = self._message_content(message.get("content"))
        tool_calls = []
        for item in message.get("tool_calls", ()) or ():
            function_payload = item.get("function", {})
            try:
                arguments = json.loads(function_payload.get("arguments", "{}"))
            except json.JSONDecodeError as exc:
                raise QueryExecutionFailure("Live LLM tool arguments were not valid JSON.") from exc
            tool_calls.append(
                LlmToolCall(
                    id=item.get("id", ""),
                    name=function_payload.get("name", ""),
                    arguments=arguments,
                )
            )
        return LlmResponse(message=LlmAssistantMessage(content=content, tool_calls=tuple(tool_calls)))

    def _message_content(self, content: Any) -> str:
        if content is None:
            return ""
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            fragments = []
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    fragments.append(item.get("text", ""))
            return "\n".join(fragment for fragment in fragments if fragment)
        return str(content)
