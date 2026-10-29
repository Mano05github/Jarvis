"""Validated provider configuration with secret-free display helpers."""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

from jarvis.contracts import GatewayConfig


def load_gateway_config(path: Path) -> GatewayConfig:
    """Load TOML while deriving immutable profile IDs from table names."""

    payload = tomllib.loads(path.read_text(encoding="utf-8-sig"))
    raw_profiles = payload.get("profiles")
    if not isinstance(raw_profiles, dict) or not raw_profiles:
        raise ValueError("LLM configuration requires at least one provider profile")
    profiles: dict[str, Any] = {}
    for name, raw_profile in raw_profiles.items():
        if not isinstance(name, str) or not isinstance(raw_profile, dict):
            raise ValueError("provider profiles must be named TOML tables")
        profiles[name] = {"profile_id": name, **raw_profile}
    return GatewayConfig.model_validate(
        {
            "schema_version": payload.get("schema_version", "1.0"),
            "default_profile": payload.get("default_profile"),
            "fallback_order": payload.get("fallback_order", []),
            "routing": payload.get("routing", {}),
            "profiles": profiles,
        }
    )


def redacted_gateway_config(config: GatewayConfig) -> dict[str, Any]:
    """Return operational metadata without ever resolving or displaying secrets."""

    return {
        "schema_version": config.schema_version,
        "default_profile": config.default_profile,
        "fallback_order": list(config.fallback_order),
        "routing": dict(config.routing),
        "profiles": {
            name: {
                "provider": profile.provider,
                "endpoint": profile.endpoint,
                "model": profile.model,
                "deployment": profile.deployment,
                "api_version": profile.api_version,
                "credential_reference_present": profile.credential_ref is not None,
                "model_manifest": profile.model_manifest,
                "remote": profile.remote,
                "timeout_seconds": profile.timeout_seconds,
            }
            for name, profile in config.profiles.items()
        },
    }


__all__ = ["load_gateway_config", "redacted_gateway_config"]
