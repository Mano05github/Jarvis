from __future__ import annotations

import json
import urllib.error
from io import BytesIO
from typing import Any

import pytest

from jarvis.contracts import (
    LLMMessage,
    LLMPrivacyClass,
    LLMRequest,
    ProviderKind,
    ProviderProfile,
    ProviderState,
)
from jarvis.llm import (
    AnthropicProvider,
    AzureOpenAIProvider,
    InMemorySecretStore,
    OpenAICompatibleProvider,
    ProviderError,
    ProviderErrorCode,
)
from jarvis.llm.base import UrllibJsonTransport


def request_fixture() -> LLMRequest:
    return LLMRequest(
        purpose="test",
        system_instructions="Return JSON.",
        messages=(LLMMessage(role="user", content="hello"),),
        response_schema="InteractionEnvelope-v1",
        privacy_class=LLMPrivacyClass.REMOTE_ALLOWED,
    )


class Response:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload

    def __enter__(self) -> Response:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self, _limit: int) -> bytes:
        return self.payload


class StaticTransport:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload

    def post_json(self, **_kwargs: object) -> tuple[dict[str, Any], float]:
        return self.payload, 1.5


class BrokenSecrets(InMemorySecretStore):
    def get(self, reference: str) -> str | None:
        raise OSError(reference)


def openai_profile(**updates: object) -> ProviderProfile:
    fields: dict[str, object] = {
        "profile_id": "openai",
        "provider": ProviderKind.OPENAI,
        "model": "model",
        "credential_ref": "secret",
        "remote": True,
    }
    fields.update(updates)
    return ProviderProfile(**fields)


def azure_profile() -> ProviderProfile:
    return ProviderProfile(
        profile_id="azure",
        provider=ProviderKind.AZURE_OPENAI,
        endpoint="https://azure.example.test",
        deployment="deployment/name",
        api_version="2026-01-01 preview",
        credential_ref="secret",
        remote=True,
    )


def anthropic_profile() -> ProviderProfile:
    return ProviderProfile(
        profile_id="anthropic",
        provider=ProviderKind.ANTHROPIC,
        model="model",
        api_version="2026-version",
        credential_ref="secret",
        remote=True,
    )


def test_transport_rejects_invalid_configuration() -> None:
    with pytest.raises(ValueError, match="too small"):
        UrllibJsonTransport(1024)


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        (b"not-json", "valid JSON"),
        (json.dumps([1, 2]).encode(), "JSON object"),
        (b"\xff", "valid JSON"),
    ],
)
def test_transport_rejects_malformed_responses(
    monkeypatch: pytest.MonkeyPatch, payload: bytes, message: str
) -> None:
    monkeypatch.setattr("urllib.request.urlopen", lambda *_args, **_kwargs: Response(payload))

    with pytest.raises(ProviderError, match=message):
        UrllibJsonTransport().post_json(
            url="https://example.test",
            headers={},
            payload={},
            timeout_seconds=1,
        )


def test_transport_accepts_object_and_enforces_size(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda *_args, **_kwargs: Response(b'{"ok":true}'),
    )
    decoded, latency = UrllibJsonTransport().post_json(
        url="https://example.test", headers={}, payload={}, timeout_seconds=1
    )
    assert decoded == {"ok": True}
    assert latency >= 0

    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda *_args, **_kwargs: Response(b"x" * 4097),
    )
    with pytest.raises(ProviderError, match="size limit"):
        UrllibJsonTransport(4096).post_json(
            url="https://example.test", headers={}, payload={}, timeout_seconds=1
        )


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (
            urllib.error.HTTPError("u", 401, "", None, BytesIO(b"{}")),
            ProviderErrorCode.AUTHENTICATION_FAILED,
        ),
        (
            urllib.error.HTTPError("u", 429, "", None, BytesIO(b"{}")),
            ProviderErrorCode.RATE_LIMITED,
        ),
        (
            urllib.error.HTTPError("u", 422, "", None, BytesIO(b"{}")),
            ProviderErrorCode.INVALID_RESPONSE,
        ),
        (
            urllib.error.HTTPError("u", 503, "", None, BytesIO(b"{}")),
            ProviderErrorCode.MODEL_UNAVAILABLE,
        ),
        (TimeoutError(), ProviderErrorCode.DEADLINE_EXCEEDED),
        (urllib.error.URLError("offline"), ProviderErrorCode.NETWORK_UNAVAILABLE),
    ],
)
def test_transport_normalizes_network_errors(
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
    code: ProviderErrorCode,
) -> None:
    def fail(*_args: object, **_kwargs: object) -> None:
        raise error

    monkeypatch.setattr("urllib.request.urlopen", fail)
    with pytest.raises(ProviderError) as caught:
        UrllibJsonTransport().post_json(
            url="https://example.test", headers={}, payload={}, timeout_seconds=1
        )
    assert caught.value.code is code


def test_http_detail_drops_unsafe_or_oversized_fields() -> None:
    unsafe = urllib.error.HTTPError(
        "u",
        400,
        "",
        None,
        BytesIO(b'{"error":{"code":"contains spaces","type":7}}'),
    )
    assert UrllibJsonTransport()._safe_http_error_detail(unsafe) == ""

    oversized = urllib.error.HTTPError("u", 400, "", None, BytesIO(b"x" * 4097))
    assert UrllibJsonTransport(4096)._safe_http_error_detail(oversized) == ""


def test_adapter_constructors_and_health_fail_closed() -> None:
    local = ProviderProfile(
        profile_id="local",
        provider=ProviderKind.OLLAMA,
        endpoint="http://127.0.0.1:11434/v1",
        model="model",
        remote=False,
    )
    empty = InMemorySecretStore()
    assert OpenAICompatibleProvider(local, empty).health().state is ProviderState.HEALTHY
    remote_health = OpenAICompatibleProvider(openai_profile(), empty).health()
    assert remote_health.state is ProviderState.UNAVAILABLE
    assert AzureOpenAIProvider(azure_profile(), empty).health().state is ProviderState.UNAVAILABLE
    assert AnthropicProvider(anthropic_profile(), empty).health().state is ProviderState.UNAVAILABLE

    with pytest.raises(ValueError, match="unsupported"):
        OpenAICompatibleProvider(azure_profile(), empty)
    with pytest.raises(ValueError, match="Azure"):
        AzureOpenAIProvider(openai_profile(), empty)
    with pytest.raises(ValueError, match="Anthropic"):
        AnthropicProvider(openai_profile(), empty)


@pytest.mark.parametrize(
    "provider_factory",
    [
        lambda secrets: OpenAICompatibleProvider(openai_profile(), secrets),
        lambda secrets: AzureOpenAIProvider(azure_profile(), secrets),
        lambda secrets: AnthropicProvider(anthropic_profile(), secrets),
    ],
)
@pytest.mark.parametrize("secrets", [InMemorySecretStore(), BrokenSecrets()])
def test_adapters_normalize_missing_or_unreadable_credentials(
    provider_factory: Any, secrets: InMemorySecretStore
) -> None:
    with pytest.raises(ProviderError) as caught:
        provider_factory(secrets).complete(request_fixture())
    assert caught.value.code is ProviderErrorCode.NOT_CONFIGURED


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({}, "omitted assistant content"),
        ({"choices": [{"message": {"content": 7}}]}, "must be text"),
        ({"choices": [{"message": {"content": "not-json"}}]}, "not a JSON object"),
        ({"choices": [{"message": {"content": "[]"}}]}, "one JSON object"),
    ],
)
def test_openai_adapter_rejects_invalid_provider_shapes(
    payload: dict[str, Any], message: str
) -> None:
    secrets = InMemorySecretStore()
    secrets.put("secret", "value")
    provider = OpenAICompatibleProvider(openai_profile(), secrets, StaticTransport(payload))
    with pytest.raises(ProviderError, match=message):
        provider.complete(request_fixture())


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({}, "omitted assistant content"),
        ({"choices": [{"message": {"content": 7}}]}, "must be text"),
        ({"choices": [{"message": {"content": "bad"}}]}, "not a JSON object"),
        ({"choices": [{"message": {"content": "[]"}}]}, "one JSON object"),
    ],
)
def test_azure_adapter_rejects_invalid_provider_shapes(
    payload: dict[str, Any], message: str
) -> None:
    secrets = InMemorySecretStore()
    secrets.put("secret", "value")
    provider = AzureOpenAIProvider(azure_profile(), secrets, StaticTransport(payload))
    with pytest.raises(ProviderError, match=message):
        provider.complete(request_fixture())


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({}, "omitted content"),
        ({"content": []}, "text block"),
        ({"content": [{"type": "text", "text": "bad"}]}, "not a JSON object"),
        ({"content": [{"type": "text", "text": "[]"}]}, "one JSON object"),
    ],
)
def test_anthropic_adapter_rejects_invalid_provider_shapes(
    payload: dict[str, Any], message: str
) -> None:
    secrets = InMemorySecretStore()
    secrets.put("secret", "value")
    provider = AnthropicProvider(anthropic_profile(), secrets, StaticTransport(payload))
    with pytest.raises(ProviderError, match=message):
        provider.complete(request_fixture())
