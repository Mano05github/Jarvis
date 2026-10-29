"""Azure OpenAI chat-completions adapter behind the canonical Jarvis contract."""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import quote

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


class AzureOpenAIProvider:
    """Use an explicitly configured Azure deployment; never infer API versions."""

    def __init__(
        self,
        profile: ProviderProfile,
        secrets: SecretStore,
        transport: JsonTransport | None = None,
    ) -> None:
        if profile.provider is not ProviderKind.AZURE_OPENAI:
            raise ValueError("Azure adapter requires an Azure OpenAI profile")
        self.profile = profile
        self.secrets = secrets
        self.transport = transport or UrllibJsonTransport()

    def capabilities(self) -> ModelCapabilities:
        return ModelCapabilities(
            streaming=False,
            structured_output=True,
            json_schema=False,
            usage_reporting=True,
        )

    def health(self) -> ProviderHealth:
        credential_ref = self.profile.credential_ref
        configured = credential_ref is not None and self.secrets.contains(credential_ref)
        return ProviderHealth(
            profile_id=self.profile.profile_id,
            provider=self.profile.provider,
            state=ProviderState.HEALTHY if configured else ProviderState.UNAVAILABLE,
            detail=None if configured else "credential is not configured",
        )

    def _url(self) -> str:
        assert self.profile.endpoint is not None
        assert self.profile.deployment is not None
        assert self.profile.api_version is not None
        endpoint = self.profile.endpoint.rstrip("/")
        deployment = quote(self.profile.deployment, safe="")
        api_version = quote(self.profile.api_version, safe="")
        return (
            f"{endpoint}/openai/deployments/{deployment}/chat/completions?api-version={api_version}"
        )

    def complete(self, request: LLMRequest) -> LLMResponse:
        assert self.profile.credential_ref is not None
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
        protocol = {
            "request_id": str(request.request_id),
            "response_schema": request.response_schema,
            "trusted_context": request.context,
        }
        system_content = (
            request.system_instructions
            + "\n\nJARVIS_PROTOCOL\n"
            + json.dumps(protocol, ensure_ascii=False, separators=(",", ":"))
        )
        messages: list[dict[str, str]] = [{"role": "system", "content": system_content}]
        messages.extend(
            {"role": message.role, "content": message.content} for message in request.messages
        )
        payload: dict[str, Any] = {
            "messages": messages,
            "max_completion_tokens": request.maximum_output_tokens,
            "response_format": {"type": "json_object"},
        }
        decoded, latency_ms = self.transport.post_json(
            url=self._url(),
            headers={"Content-Type": "application/json", "api-key": credential},
            payload=payload,
            timeout_seconds=min(self.profile.timeout_seconds, request.deadline_ms / 1_000),
        )
        try:
            choice = decoded["choices"][0]
            content = choice["message"]["content"]
        except (KeyError, IndexError, TypeError) as error:
            raise ProviderError(
                ProviderErrorCode.INVALID_RESPONSE,
                "Azure response omitted assistant content",
            ) from error
        if not isinstance(content, str):
            raise ProviderError(
                ProviderErrorCode.INVALID_RESPONSE, "Azure assistant content must be text"
            )
        try:
            structured = json.loads(content)
        except json.JSONDecodeError as error:
            raise ProviderError(
                ProviderErrorCode.INVALID_RESPONSE,
                "Azure assistant content was not a JSON object",
            ) from error
        if not isinstance(structured, dict):
            raise ProviderError(
                ProviderErrorCode.INVALID_RESPONSE,
                "Azure assistant content must contain one JSON object",
            )
        usage = decoded.get("usage", {})
        return LLMResponse(
            request_id=request.request_id,
            profile_id=self.profile.profile_id,
            provider=self.profile.provider,
            model=self.profile.deployment or "azure-deployment",
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


__all__ = ["AzureOpenAIProvider"]
