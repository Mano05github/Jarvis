"""Adapters for OpenAI and explicit OpenAI-compatible HTTP endpoints."""

from __future__ import annotations

import json
from typing import Any

from jarvis.contracts import (
    LLMRequest,
    LLMResponse,
    LLMUsage,
    ModelCapabilities,
    ProviderHealth,
    ProviderKind,
    ProviderProfile,
    ProviderState,
)
from jarvis.llm.base import JsonTransport, ProviderError, ProviderErrorCode, UrllibJsonTransport
from jarvis.llm.secrets import SecretStore

_SUPPORTED = {
    ProviderKind.OPENAI,
    ProviderKind.OPENAI_COMPATIBLE,
    ProviderKind.OLLAMA,
    ProviderKind.LLAMA_CPP,
}


class OpenAICompatibleProvider:
    """Translate the Jarvis contract to a configured chat-completions endpoint."""

    def __init__(
        self,
        profile: ProviderProfile,
        secrets: SecretStore,
        transport: JsonTransport | None = None,
    ) -> None:
        if profile.provider not in _SUPPORTED:
            raise ValueError("OpenAI-compatible adapter received an unsupported profile")
        self.profile = profile
        self.secrets = secrets
        self.transport = transport or UrllibJsonTransport()

    def capabilities(self) -> ModelCapabilities:
        return ModelCapabilities(
            structured_output=True,
            usage_reporting=True,
        )

    def health(self) -> ProviderHealth:
        reference = self.profile.credential_ref
        configured = reference is None or self.secrets.contains(reference)
        return ProviderHealth(
            profile_id=self.profile.profile_id,
            provider=self.profile.provider,
            state=ProviderState.HEALTHY if configured else ProviderState.UNAVAILABLE,
            detail=None if configured else "credential is not configured",
        )

    def _url(self) -> str:
        endpoint = self.profile.endpoint
        if self.profile.provider is ProviderKind.OPENAI and endpoint is None:
            endpoint = "https://api.openai.com/v1"
        assert endpoint is not None
        base = endpoint.rstrip("/")
        return base if base.endswith("/chat/completions") else f"{base}/chat/completions"

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        reference = self.profile.credential_ref
        if reference is not None:
            try:
                credential = self.secrets.get(reference)
            except OSError as error:
                raise ProviderError(
                    ProviderErrorCode.NOT_CONFIGURED,
                    "credential is not readable by the current Windows identity",
                ) from error
            if credential is None:
                raise ProviderError(
                    ProviderErrorCode.NOT_CONFIGURED,
                    f"credential is not configured for profile {self.profile.profile_id}",
                )
            headers["Authorization"] = f"Bearer {credential}"
        return headers

    def complete(self, request: LLMRequest) -> LLMResponse:
        protocol = {
            "request_id": str(request.request_id),
            "response_schema": request.response_schema,
            "trusted_context": request.context,
        }
        system = (
            request.system_instructions
            + "\n\nJARVIS_PROTOCOL\n"
            + json.dumps(protocol, ensure_ascii=False, separators=(",", ":"))
        )
        messages: list[dict[str, str]] = [{"role": "system", "content": system}]
        messages.extend(
            {"role": message.role, "content": message.content} for message in request.messages
        )
        payload: dict[str, Any] = {
            "model": self.profile.model,
            "messages": messages,
            "temperature": request.temperature,
            "max_tokens": request.maximum_output_tokens,
            "response_format": {"type": "json_object"},
        }
        decoded, latency_ms = self.transport.post_json(
            url=self._url(),
            headers=self._headers(),
            payload=payload,
            timeout_seconds=min(self.profile.timeout_seconds, request.deadline_ms / 1_000),
        )
        try:
            choice = decoded["choices"][0]
            content = choice["message"]["content"]
        except (KeyError, IndexError, TypeError) as error:
            raise ProviderError(
                ProviderErrorCode.INVALID_RESPONSE,
                "provider response omitted assistant content",
            ) from error
        if not isinstance(content, str):
            raise ProviderError(
                ProviderErrorCode.INVALID_RESPONSE, "assistant content must be text"
            )
        try:
            structured = json.loads(content)
        except json.JSONDecodeError as error:
            raise ProviderError(
                ProviderErrorCode.INVALID_RESPONSE,
                "assistant content was not a JSON object",
            ) from error
        if not isinstance(structured, dict):
            raise ProviderError(
                ProviderErrorCode.INVALID_RESPONSE,
                "assistant content must contain one JSON object",
            )
        usage = decoded.get("usage", {})
        return LLMResponse(
            request_id=request.request_id,
            profile_id=self.profile.profile_id,
            provider=self.profile.provider,
            model=self.profile.model or "configured-model",
            text=content,
            structured_output=structured,
            finish_reason=(
                str(choice.get("finish_reason"))
                if isinstance(choice, dict) and choice.get("finish_reason") is not None
                else None
            ),
            usage=LLMUsage(
                input_tokens=(
                    int(usage["prompt_tokens"])
                    if isinstance(usage, dict) and isinstance(usage.get("prompt_tokens"), int)
                    else None
                ),
                output_tokens=(
                    int(usage["completion_tokens"])
                    if isinstance(usage, dict) and isinstance(usage.get("completion_tokens"), int)
                    else None
                ),
            ),
            latency_ms=latency_ms,
        )


__all__ = ["OpenAICompatibleProvider"]
