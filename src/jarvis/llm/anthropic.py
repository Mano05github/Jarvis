"""Anthropic Messages API adapter behind the canonical Jarvis contract."""

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


class AnthropicProvider:
    def __init__(
        self,
        profile: ProviderProfile,
        secrets: SecretStore,
        transport: JsonTransport | None = None,
    ) -> None:
        if profile.provider is not ProviderKind.ANTHROPIC:
            raise ValueError("Anthropic adapter requires an Anthropic profile")
        self.profile = profile
        self.secrets = secrets
        self.transport = transport or UrllibJsonTransport()

    def capabilities(self) -> ModelCapabilities:
        return ModelCapabilities(structured_output=True, usage_reporting=True)

    def health(self) -> ProviderHealth:
        assert self.profile.credential_ref is not None
        configured = self.secrets.contains(self.profile.credential_ref)
        return ProviderHealth(
            profile_id=self.profile.profile_id,
            provider=self.profile.provider,
            state=ProviderState.HEALTHY if configured else ProviderState.UNAVAILABLE,
            detail=None if configured else "credential is not configured",
        )

    def complete(self, request: LLMRequest) -> LLMResponse:
        assert self.profile.credential_ref is not None
        assert self.profile.api_version is not None
        try:
            credential = self.secrets.get(self.profile.credential_ref)
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
        endpoint = (self.profile.endpoint or "https://api.anthropic.com").rstrip("/")
        url = endpoint if endpoint.endswith("/v1/messages") else f"{endpoint}/v1/messages"
        protocol = {
            "request_id": str(request.request_id),
            "response_schema": request.response_schema,
            "trusted_context": request.context,
        }
        payload: dict[str, Any] = {
            "model": self.profile.model,
            "system": request.system_instructions
            + "\n\nJARVIS_PROTOCOL\n"
            + json.dumps(protocol, ensure_ascii=False, separators=(",", ":")),
            "messages": [
                {"role": message.role, "content": message.content} for message in request.messages
            ],
            "temperature": request.temperature,
            "max_tokens": request.maximum_output_tokens,
        }
        decoded, latency_ms = self.transport.post_json(
            url=url,
            headers={
                "Content-Type": "application/json",
                "x-api-key": credential,
                "anthropic-version": self.profile.api_version,
            },
            payload=payload,
            timeout_seconds=min(self.profile.timeout_seconds, request.deadline_ms / 1_000),
        )
        blocks = decoded.get("content")
        if not isinstance(blocks, list):
            raise ProviderError(
                ProviderErrorCode.INVALID_RESPONSE, "Anthropic response omitted content"
            )
        content = next(
            (
                block.get("text")
                for block in blocks
                if isinstance(block, dict)
                and block.get("type") == "text"
                and isinstance(block.get("text"), str)
            ),
            None,
        )
        if content is None:
            raise ProviderError(
                ProviderErrorCode.INVALID_RESPONSE,
                "Anthropic response omitted a text block",
            )
        try:
            structured = json.loads(content)
        except json.JSONDecodeError as error:
            raise ProviderError(
                ProviderErrorCode.INVALID_RESPONSE,
                "Anthropic text block was not a JSON object",
            ) from error
        if not isinstance(structured, dict):
            raise ProviderError(
                ProviderErrorCode.INVALID_RESPONSE,
                "Anthropic text block must contain one JSON object",
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
                str(decoded["stop_reason"]) if decoded.get("stop_reason") is not None else None
            ),
            usage=LLMUsage(
                input_tokens=(
                    int(usage["input_tokens"])
                    if isinstance(usage, dict) and isinstance(usage.get("input_tokens"), int)
                    else None
                ),
                output_tokens=(
                    int(usage["output_tokens"])
                    if isinstance(usage, dict) and isinstance(usage.get("output_tokens"), int)
                    else None
                ),
            ),
            latency_ms=latency_ms,
        )


__all__ = ["AnthropicProvider"]
