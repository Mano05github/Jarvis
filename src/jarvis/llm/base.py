"""Provider interface, normalized errors and bounded JSON transport."""

from __future__ import annotations

import json
import string
import time
import urllib.error
import urllib.request
from enum import StrEnum
from typing import Any, Protocol

from jarvis.contracts import (
    LLMRequest,
    LLMResponse,
    ModelCapabilities,
    ProviderHealth,
    ProviderProfile,
)


class ProviderErrorCode(StrEnum):
    AUTHENTICATION_FAILED = "authentication_failed"
    RATE_LIMITED = "rate_limited"
    MODEL_UNAVAILABLE = "model_unavailable"
    NETWORK_UNAVAILABLE = "network_unavailable"
    DEADLINE_EXCEEDED = "deadline_exceeded"
    INVALID_RESPONSE = "invalid_response"
    PRIVACY_ROUTE_UNAVAILABLE = "privacy_route_unavailable"
    NOT_CONFIGURED = "not_configured"


class ProviderError(RuntimeError):
    def __init__(self, code: ProviderErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code


class LLMProvider(Protocol):
    profile: ProviderProfile

    def capabilities(self) -> ModelCapabilities: ...

    def health(self) -> ProviderHealth: ...

    def complete(self, request: LLMRequest) -> LLMResponse: ...


class JsonTransport(Protocol):
    def post_json(
        self,
        *,
        url: str,
        headers: dict[str, str],
        payload: dict[str, Any],
        timeout_seconds: float,
    ) -> tuple[dict[str, Any], float]: ...


class UrllibJsonTransport:
    """Dependency-free HTTPS JSON transport with bounded response bodies."""

    def __init__(self, maximum_response_bytes: int = 2 * 1024 * 1024) -> None:
        if maximum_response_bytes < 4096:
            raise ValueError("maximum response size is too small")
        self.maximum_response_bytes = maximum_response_bytes

    def post_json(
        self,
        *,
        url: str,
        headers: dict[str, str],
        payload: dict[str, Any],
        timeout_seconds: float,
    ) -> tuple[dict[str, Any], float]:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(url, data=body, headers=headers, method="POST")
        started = time.perf_counter()
        try:
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                received = response.read(self.maximum_response_bytes + 1)
        except urllib.error.HTTPError as error:
            if error.code in {401, 403}:
                code = ProviderErrorCode.AUTHENTICATION_FAILED
            elif error.code == 429:
                code = ProviderErrorCode.RATE_LIMITED
            elif error.code in {400, 422}:
                code = ProviderErrorCode.INVALID_RESPONSE
            else:
                code = ProviderErrorCode.MODEL_UNAVAILABLE
            detail = self._safe_http_error_detail(error)
            raise ProviderError(
                code,
                f"provider returned HTTP {error.code}{detail}",
            ) from error
        except TimeoutError as error:
            raise ProviderError(
                ProviderErrorCode.DEADLINE_EXCEEDED, "provider timed out"
            ) from error
        except urllib.error.URLError as error:
            raise ProviderError(
                ProviderErrorCode.NETWORK_UNAVAILABLE, "provider network request failed"
            ) from error
        elapsed_ms = (time.perf_counter() - started) * 1_000
        if len(received) > self.maximum_response_bytes:
            raise ProviderError(
                ProviderErrorCode.INVALID_RESPONSE, "provider response exceeded size limit"
            )
        try:
            decoded = json.loads(received.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ProviderError(
                ProviderErrorCode.INVALID_RESPONSE, "provider response was not valid JSON"
            ) from error
        if not isinstance(decoded, dict):
            raise ProviderError(
                ProviderErrorCode.INVALID_RESPONSE, "provider response must be a JSON object"
            )
        return decoded, elapsed_ms

    def _safe_http_error_detail(self, error: urllib.error.HTTPError) -> str:
        """Return only bounded machine fields; never retain an error-body message."""

        try:
            received = error.read(self.maximum_response_bytes + 1)
            if len(received) > self.maximum_response_bytes:
                return ""
            decoded = json.loads(received.decode("utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return ""
        if not isinstance(decoded, dict) or not isinstance(decoded.get("error"), dict):
            return ""
        payload = decoded["error"]
        allowed = frozenset(string.ascii_letters + string.digits + "._-[]")
        fields: list[str] = []
        for name in ("code", "type", "param"):
            value = payload.get(name)
            if (
                isinstance(value, str)
                and 0 < len(value) <= 80
                and all(character in allowed for character in value)
            ):
                fields.append(f"{name}={value}")
        return f" ({' '.join(fields)})" if fields else ""


__all__ = [
    "JsonTransport",
    "LLMProvider",
    "ProviderError",
    "ProviderErrorCode",
    "UrllibJsonTransport",
]
