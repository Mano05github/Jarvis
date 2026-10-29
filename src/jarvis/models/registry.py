"""Integrity and provenance records for local model assets."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl

from jarvis.storage import StorageLayout


class ModelManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"] = "1.0"
    model_id: str = Field(min_length=1)
    function: Literal["stt", "tts", "vad", "wakeword", "llm"]
    engine: str = Field(min_length=1)
    version: str = Field(min_length=1)
    quantization: str | None = None
    languages: tuple[str, ...]
    source_url: HttpUrl
    source_expected_bytes: int | None = Field(default=None, gt=0)
    source_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    license_name: str = Field(min_length=1)
    expected_bytes: int = Field(gt=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    relative_file: str = Field(min_length=1)
    status: Literal["declared", "downloaded", "verified", "certified", "rejected"] = "declared"

    def asset_path(self, layout: StorageLayout) -> Path:
        return layout.path("models", self.function, self.relative_file)


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def verify_model(manifest: ModelManifest, layout: StorageLayout) -> list[str]:
    asset = manifest.asset_path(layout)
    if not asset.is_file():
        return [f"model asset not found: {asset}"]

    errors: list[str] = []
    if manifest.status == "rejected":
        errors.append("model status is rejected")
    actual_size = asset.stat().st_size
    if actual_size != manifest.expected_bytes:
        errors.append(f"size mismatch: expected {manifest.expected_bytes}, got {actual_size}")
    actual_sha = sha256_file(asset)
    if actual_sha != manifest.sha256:
        errors.append(f"sha256 mismatch: expected {manifest.sha256}, got {actual_sha}")
    return errors


def load_manifest(path: Path) -> ModelManifest:
    return ModelManifest.model_validate(json.loads(path.read_text(encoding="utf-8-sig")))
