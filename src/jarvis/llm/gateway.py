"""Purpose- and privacy-aware routing across normalized LLM providers."""

from __future__ import annotations

import json
from collections.abc import Mapping

from jarvis.contracts import (
    DataClass,
    GatewayConfig,
    InteractionEnvelope,
    LLMPrivacyClass,
    LLMRequest,
    LLMResponse,
)
from jarvis.llm.base import LLMProvider, ProviderError, ProviderErrorCode


class LLMGateway:
    def __init__(self, config: GatewayConfig, providers: Mapping[str, LLMProvider]) -> None:
        missing = set(config.profiles).difference(providers)
        if missing:
            raise ValueError(f"providers are not registered for: {', '.join(sorted(missing))}")
        for profile_id, provider in providers.items():
            configured = config.profiles.get(profile_id)
            if configured is None or provider.profile != configured:
                raise ValueError("registered provider does not match gateway configuration")
        self.config = config
        self.providers = dict(providers)

    def _candidate_profiles(self, request: LLMRequest) -> list[str]:
        preferred = self.config.routing.get(request.purpose, self.config.default_profile)
        return list(dict.fromkeys((preferred, *self.config.fallback_order)))

    @staticmethod
    def _privacy_allows(request: LLMRequest, *, remote: bool) -> bool:
        if not remote:
            return True
        if request.privacy_class is LLMPrivacyClass.LOCAL_ONLY:
            return False
        return not request.data_classes.intersection({DataClass.SECRET, DataClass.PROHIBITED})

    def complete_detailed(self, request: LLMRequest) -> tuple[InteractionEnvelope, LLMResponse]:
        errors: list[str] = []
        provider_error_codes: list[ProviderErrorCode] = []
        for profile_id in self._candidate_profiles(request):
            profile = self.config.profiles[profile_id]
            if not self._privacy_allows(request, remote=profile.remote):
                errors.append(f"{profile_id}: privacy route denied")
                continue
            provider = self.providers[profile_id]
            try:
                response = provider.complete(request)
            except ProviderError as error:
                errors.append(f"{profile_id}: {error.code.value} ({error})")
                provider_error_codes.append(error.code)
                continue
            if response.request_id != request.request_id:
                errors.append(f"{profile_id}: mismatched request ID")
                continue
            payload = response.structured_output
            if payload is None:
                try:
                    loaded = json.loads(response.text)
                except json.JSONDecodeError:
                    errors.append(f"{profile_id}: invalid structured output")
                    continue
                if not isinstance(loaded, dict):
                    errors.append(f"{profile_id}: structured output is not an object")
                    continue
                payload = loaded
            try:
                envelope = InteractionEnvelope.model_validate(payload)
            except ValueError:
                errors.append(f"{profile_id}: interaction contract rejected output")
                continue
            if envelope.request_id != request.request_id:
                errors.append(f"{profile_id}: envelope request ID mismatch")
                continue
            return envelope, response
        detail = "; ".join(errors) if errors else "no provider profiles were available"
        raise ProviderError(
            (
                provider_error_codes[-1]
                if provider_error_codes
                else ProviderErrorCode.PRIVACY_ROUTE_UNAVAILABLE
            ),
            f"no certified provider completed the request: {detail}",
        )

    def complete(self, request: LLMRequest) -> InteractionEnvelope:
        envelope, _response = self.complete_detailed(request)
        return envelope


__all__ = ["LLMGateway"]
