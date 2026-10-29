from __future__ import annotations

import json
import os
import urllib.error
from io import BytesIO
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from jarvis.contracts import (
    GatewayConfig,
    InteractionEnvelope,
    InteractionMode,
    LLMMessage,
    LLMPrivacyClass,
    LLMRequest,
    ProviderKind,
    ProviderProfile,
)
from jarvis.llm import (
    AnthropicProvider,
    AzureOpenAIProvider,
    DPAPISecretStore,
    FakeLLMProvider,
    InMemorySecretStore,
    LLMGateway,
    OpenAICompatibleProvider,
    ProviderError,
    ProviderErrorCode,
    build_providers,
    load_gateway_config,
    redacted_gateway_config,
)
from jarvis.llm.base import UrllibJsonTransport

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def request_fixture(*, privacy: LLMPrivacyClass = LLMPrivacyClass.REMOTE_ALLOWED) -> LLMRequest:
    return LLMRequest(
        purpose="companion",
        system_instructions="Return one InteractionEnvelope.",
        messages=(LLMMessage(role="user", content="Jarvis, enaku bore adikudhu"),),
        response_schema="InteractionEnvelope-v1",
        context={"active_app": None},
        privacy_class=privacy,
    )


def chat_fixture(request_id: UUID | None = None) -> InteractionEnvelope:
    return InteractionEnvelope(
        request_id=request_id or uuid4(),
        mode=InteractionMode.CHAT,
        reply="Appadiya? Konjam pesalama?",
    )


def test_base_gateway_configuration_is_offline_and_secret_free() -> None:
    config = load_gateway_config(PROJECT_ROOT / "config" / "base" / "llm-providers.toml")
    redacted = redacted_gateway_config(config)

    assert config.default_profile == "offline-fixture"
    assert config.profiles["offline-fixture"].remote is False
    assert '"credential_ref":' not in json.dumps(redacted)


def test_provider_profiles_enforce_remote_https_and_local_loopback() -> None:
    with pytest.raises(ValidationError, match="must use HTTPS"):
        ProviderProfile(
            profile_id="bad-remote",
            provider=ProviderKind.OPENAI,
            endpoint="http://api.example.test/v1",
            model="model",
            credential_ref="credential",
            remote=True,
        )
    with pytest.raises(ValidationError, match="must use loopback"):
        ProviderProfile(
            profile_id="bad-local",
            provider=ProviderKind.OLLAMA,
            endpoint="http://192.168.1.20:11434",
            model="model",
            remote=False,
        )


def test_gateway_routes_local_only_turn_away_from_remote_profile() -> None:
    remote = ProviderProfile(
        profile_id="remote",
        provider=ProviderKind.FAKE,
        model="remote-fixture",
        remote=True,
    )
    local = ProviderProfile(
        profile_id="local",
        provider=ProviderKind.FAKE,
        model="local-fixture",
        remote=False,
    )
    config = GatewayConfig(
        default_profile="remote",
        fallback_order=("local",),
        routing={"companion": "remote"},
        profiles={"remote": remote, "local": local},
    )
    remote_provider = FakeLLMProvider(remote, chat_fixture())
    local_provider = FakeLLMProvider(local, chat_fixture())
    gateway = LLMGateway(config, {"remote": remote_provider, "local": local_provider})

    result = gateway.complete(request_fixture(privacy=LLMPrivacyClass.LOCAL_ONLY))

    assert result.mode is InteractionMode.CHAT
    assert remote_provider.requests == []
    assert len(local_provider.requests) == 1


def test_gateway_preserves_safe_provider_failure_detail() -> None:
    profile = ProviderProfile(
        profile_id="failing",
        provider=ProviderKind.FAKE,
        model="fixture",
        remote=False,
    )
    config = GatewayConfig(default_profile="failing", profiles={"failing": profile})

    class FailingProvider:
        def __init__(self) -> None:
            self.profile = profile

        def complete(self, _request: LLMRequest):
            raise ProviderError(
                ProviderErrorCode.MODEL_UNAVAILABLE,
                "provider returned HTTP 404",
            )

    gateway = LLMGateway(config, {"failing": FailingProvider()})

    with pytest.raises(
        ProviderError,
        match=r"failing: model_unavailable \(provider returned HTTP 404\)",
    ):
        gateway.complete(request_fixture())


def test_http_error_detail_exposes_only_safe_machine_fields() -> None:
    body = json.dumps(
        {
            "error": {
                "code": "content_filter",
                "type": "invalid_request_error",
                "param": "messages[1]",
                "message": "sensitive echoed prompt must never appear",
            }
        }
    ).encode()
    error = urllib.error.HTTPError(
        "https://example.test",
        400,
        "Bad Request",
        hdrs=None,
        fp=BytesIO(body),
    )

    detail = UrllibJsonTransport()._safe_http_error_detail(error)

    assert detail == (" (code=content_filter type=invalid_request_error param=messages[1])")
    assert "sensitive" not in detail


class CapturingTransport:
    def __init__(self, request_id: UUID) -> None:
        self.request_id = request_id
        self.call: dict[str, Any] | None = None

    def post_json(
        self,
        *,
        url: str,
        headers: dict[str, str],
        payload: dict[str, Any],
        timeout_seconds: float,
    ) -> tuple[dict[str, Any], float]:
        self.call = {
            "url": url,
            "headers": headers,
            "payload": payload,
            "timeout_seconds": timeout_seconds,
        }
        content = chat_fixture(self.request_id).model_dump_json()
        return (
            {
                "choices": [
                    {
                        "message": {"content": content},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 8},
            },
            12.5,
        )


def test_azure_adapter_translates_canonical_request_without_network() -> None:
    request = request_fixture()
    profile = ProviderProfile(
        profile_id="azure-primary",
        provider=ProviderKind.AZURE_OPENAI,
        endpoint="https://example.openai.azure.com",
        deployment="jarvis-primary",
        api_version="configured-version",
        credential_ref="jarvis/llm/azure-primary",
        remote=True,
    )
    secrets = InMemorySecretStore()
    secrets.put("jarvis/llm/azure-primary", "fixture-secret")
    transport = CapturingTransport(request.request_id)
    provider = AzureOpenAIProvider(profile, secrets, transport)

    response = provider.complete(request)

    assert response.structured_output is not None
    assert response.usage.input_tokens == 10
    assert transport.call is not None
    assert transport.call["headers"]["api-key"] == "fixture-secret"
    assert "jarvis-primary" in transport.call["url"]
    system_message = transport.call["payload"]["messages"][0]["content"]
    assert str(request.request_id) in system_message
    assert "InteractionEnvelope-v1" in system_message


def test_openai_compatible_local_adapter_requires_no_credential() -> None:
    request = request_fixture(privacy=LLMPrivacyClass.LOCAL_ONLY)
    profile = ProviderProfile(
        profile_id="local-ollama",
        provider=ProviderKind.OLLAMA,
        endpoint="http://127.0.0.1:11434/v1",
        model="local-model",
        remote=False,
    )
    transport = CapturingTransport(request.request_id)
    provider = OpenAICompatibleProvider(profile, InMemorySecretStore(), transport)

    response = provider.complete(request)

    assert response.provider is ProviderKind.OLLAMA
    assert transport.call is not None
    assert transport.call["url"] == "http://127.0.0.1:11434/v1/chat/completions"
    assert "Authorization" not in transport.call["headers"]


class AnthropicTransport:
    def __init__(self, request_id: UUID) -> None:
        self.request_id = request_id
        self.call: dict[str, Any] | None = None

    def post_json(
        self,
        *,
        url: str,
        headers: dict[str, str],
        payload: dict[str, Any],
        timeout_seconds: float,
    ) -> tuple[dict[str, Any], float]:
        self.call = {
            "url": url,
            "headers": headers,
            "payload": payload,
            "timeout_seconds": timeout_seconds,
        }
        return (
            {
                "content": [
                    {"type": "text", "text": chat_fixture(self.request_id).model_dump_json()}
                ],
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 11, "output_tokens": 7},
            },
            9.0,
        )


def test_anthropic_adapter_uses_explicit_version_without_network() -> None:
    request = request_fixture()
    profile = ProviderProfile(
        profile_id="anthropic-primary",
        provider=ProviderKind.ANTHROPIC,
        endpoint="https://api.anthropic.test",
        model="owner-selected-model",
        api_version="owner-selected-version",
        credential_ref="jarvis/llm/anthropic-primary",
        remote=True,
    )
    secrets = InMemorySecretStore()
    secrets.put(profile.credential_ref or "", "fixture-secret")
    transport = AnthropicTransport(request.request_id)

    response = AnthropicProvider(profile, secrets, transport).complete(request)

    assert response.usage.output_tokens == 7
    assert transport.call is not None
    assert transport.call["headers"]["anthropic-version"] == "owner-selected-version"
    assert str(request.request_id) in transport.call["payload"]["system"]


def test_provider_factory_builds_explicit_local_adapter() -> None:
    profile = ProviderProfile(
        profile_id="local",
        provider=ProviderKind.OPENAI_COMPATIBLE,
        endpoint="http://localhost:1234/v1",
        model="owner-model",
        remote=False,
    )
    config = GatewayConfig(
        default_profile="local",
        routing={"companion": "local"},
        profiles={"local": profile},
    )

    providers = build_providers(config, InMemorySecretStore())

    assert isinstance(providers["local"], OpenAICompatibleProvider)


@pytest.mark.skipif(os.name != "nt", reason="DPAPI is a Windows facility")
def test_dpapi_store_round_trip_is_encrypted(tmp_path: Path) -> None:
    store = DPAPISecretStore(tmp_path / "secrets")
    store.put("jarvis/llm/test", "not-plaintext")

    stored = next((tmp_path / "secrets").glob("*.dpapi")).read_bytes()
    assert b"not-plaintext" not in stored
    assert store.get("jarvis/llm/test") == "not-plaintext"
    assert store.contains("jarvis/llm/test") is True
