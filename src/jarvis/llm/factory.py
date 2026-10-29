"""Construct provider adapters from validated configuration."""

from __future__ import annotations

from collections.abc import Mapping

from jarvis.contracts import GatewayConfig, InteractionEnvelope, ProviderKind
from jarvis.llm.anthropic import AnthropicProvider
from jarvis.llm.azure_openai import AzureOpenAIProvider
from jarvis.llm.base import LLMProvider
from jarvis.llm.fake import FakeLLMProvider
from jarvis.llm.openai_compatible import OpenAICompatibleProvider
from jarvis.llm.secrets import SecretStore


def build_providers(
    config: GatewayConfig,
    secrets: SecretStore,
    *,
    fake_responses: Mapping[str, InteractionEnvelope] | None = None,
) -> dict[str, LLMProvider]:
    """Build only explicit adapters; no provider is inferred from a URL or model name."""

    providers: dict[str, LLMProvider] = {}
    for profile_id, profile in config.profiles.items():
        if profile.provider is ProviderKind.AZURE_OPENAI:
            provider: LLMProvider = AzureOpenAIProvider(profile, secrets)
        elif profile.provider is ProviderKind.ANTHROPIC:
            provider = AnthropicProvider(profile, secrets)
        elif profile.provider in {
            ProviderKind.OPENAI,
            ProviderKind.OPENAI_COMPATIBLE,
            ProviderKind.OLLAMA,
            ProviderKind.LLAMA_CPP,
        }:
            provider = OpenAICompatibleProvider(profile, secrets)
        elif profile.provider is ProviderKind.FAKE:
            response = (fake_responses or {}).get(profile_id)
            if response is None:
                raise ValueError(f"fake provider {profile_id} requires an explicit response")
            provider = FakeLLMProvider(profile, response)
        else:  # pragma: no cover - enum exhaustiveness guard
            raise ValueError(f"unsupported provider kind: {profile.provider}")
        providers[profile_id] = provider
    return providers


__all__ = ["build_providers"]
