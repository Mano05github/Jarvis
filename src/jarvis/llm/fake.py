"""Deterministic provider used for offline gateway and dialogue testing."""

from __future__ import annotations

from jarvis.contracts import (
    InteractionEnvelope,
    LLMRequest,
    LLMResponse,
    ModelCapabilities,
    ProviderHealth,
    ProviderKind,
    ProviderProfile,
    ProviderState,
)


class FakeLLMProvider:
    def __init__(self, profile: ProviderProfile, response: InteractionEnvelope) -> None:
        if profile.provider is not ProviderKind.FAKE:
            raise ValueError("fake provider requires a fake profile")
        self.profile = profile
        self.response = response
        self.requests: list[LLMRequest] = []

    def capabilities(self) -> ModelCapabilities:
        return ModelCapabilities(streaming=False, structured_output=True, json_schema=True)

    def health(self) -> ProviderHealth:
        return ProviderHealth(
            profile_id=self.profile.profile_id,
            provider=self.profile.provider,
            state=ProviderState.HEALTHY,
            latency_ms=0,
        )

    def complete(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        payload = self.response.model_copy(update={"request_id": request.request_id})
        return LLMResponse(
            request_id=request.request_id,
            profile_id=self.profile.profile_id,
            provider=self.profile.provider,
            model=self.profile.model or "fixture",
            text=payload.model_dump_json(),
            structured_output=payload.model_dump(mode="json"),
            finish_reason="complete",
            latency_ms=0,
        )


__all__ = ["FakeLLMProvider"]
