"""Strict provenance records for the tiny native ONNX inference gate."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator

from jarvis.models.registry import sha256_file


class OnnxRuntimeSourceManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"]
    source_id: str = Field(min_length=1, max_length=128)
    publisher: Literal["Microsoft"]
    repository_url: HttpUrl
    release_tag: str = Field(pattern=r"^v[0-9]+\.[0-9]+\.[0-9]+$")
    release_url: HttpUrl
    published_at: datetime
    source_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    asset_name: str = Field(pattern=r"^onnxruntime-win-x64-[0-9]+\.[0-9]+\.[0-9]+\.zip$")
    asset_url: HttpUrl
    asset_bytes: int = Field(gt=0)
    asset_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    platform: Literal["windows-x64"]
    execution_provider: Literal["cpu"]
    license_spdx: Literal["MIT"]
    license_path: Literal["LICENSE"]
    license_git_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    license_bytes: int = Field(gt=0)
    license_url: HttpUrl
    archive_root: str = Field(min_length=1, max_length=128)
    required_archive_members: tuple[str, ...] = Field(min_length=4, max_length=32)
    status: Literal["inspected"]

    @model_validator(mode="after")
    def validate_official_source(self) -> OnnxRuntimeSourceManifest:
        repository = str(self.repository_url).rstrip("/")
        if repository != "https://github.com/microsoft/onnxruntime":
            raise ValueError("ONNX Runtime repository must be the official Microsoft repository")
        version = self.release_tag.removeprefix("v")
        expected_name = f"onnxruntime-win-x64-{version}.zip"
        expected_release = f"{repository}/releases/tag/{self.release_tag}"
        expected_asset = f"{repository}/releases/download/{self.release_tag}/{expected_name}"
        expected_license = (
            f"https://raw.githubusercontent.com/microsoft/onnxruntime/{self.release_tag}/LICENSE"
        )
        expected_root = f"onnxruntime-win-x64-{version}"
        if self.asset_name != expected_name:
            raise ValueError("ONNX Runtime asset name does not match the release tag")
        if str(self.release_url) != expected_release:
            raise ValueError("ONNX Runtime release URL does not match the release tag")
        if str(self.asset_url) != expected_asset:
            raise ValueError("ONNX Runtime asset URL is not the official release asset")
        if str(self.license_url) != expected_license:
            raise ValueError("ONNX Runtime licence URL is not bound to the release tag")
        if self.archive_root != expected_root:
            raise ValueError("ONNX Runtime archive root does not match the release tag")
        if self.published_at.tzinfo is None:
            raise ValueError("ONNX Runtime publication timestamp must include a timezone")
        for member in self.required_archive_members:
            path = PurePosixPath(member)
            if (
                path.is_absolute()
                or ".." in path.parts
                or "\\" in member
                or not member.startswith(f"{self.archive_root}/")
            ):
                raise ValueError("ONNX Runtime archive member escapes the pinned root")
        required_suffixes = {
            "LICENSE",
            "include/onnxruntime_c_api.h",
            "lib/onnxruntime.dll",
            "lib/onnxruntime.lib",
        }
        actual_suffixes = {
            str(PurePosixPath(member).relative_to(self.archive_root))
            for member in self.required_archive_members
        }
        if not required_suffixes.issubset(actual_suffixes):
            raise ValueError("ONNX Runtime required native files are incomplete")
        return self

    def canonical_sha256(self) -> str:
        encoded = json.dumps(
            self.model_dump(mode="json"),
            ensure_ascii=True,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


class TinyOnnxFixtureManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"]
    fixture_id: Literal["tiny-affine-relu-v1"]
    formula: Literal["y = Relu((x * 2) + 1)"]
    onnx_schema_tag: Literal["v1.22.0"]
    onnx_runtime_dependency_hash: str = Field(pattern=r"^[0-9a-f]{40}$")
    ir_version: Literal[8]
    opset_version: Literal[17]
    input_name: Literal["x"]
    input_type: Literal["float32"]
    input_shape: tuple[Literal[1], Literal[4]]
    input_values: tuple[float, float, float, float]
    output_name: Literal["y"]
    output_type: Literal["float32"]
    output_shape: tuple[Literal[1], Literal[4]]
    expected_output: tuple[float, float, float, float]
    model_file: Literal["model.onnx"]
    model_bytes: int = Field(gt=0, le=1024 * 1024)
    model_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    generator_file: Literal["tools/generate_tiny_onnx_fixture.py"]
    generator_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    external_data: Literal[False]
    custom_operators: Literal[False]

    @model_validator(mode="after")
    def validate_deterministic_values(self) -> TinyOnnxFixtureManifest:
        if self.input_values != (-2.0, -1.0, 0.0, 2.0):
            raise ValueError("tiny ONNX fixture input values differ from the audited vector")
        calculated = tuple(max(0.0, (value * 2.0) + 1.0) for value in self.input_values)
        if self.expected_output != calculated:
            raise ValueError("tiny ONNX fixture expected output does not match its formula")
        return self

    def canonical_sha256(self) -> str:
        encoded = json.dumps(
            self.model_dump(mode="json"),
            ensure_ascii=True,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


def load_onnxruntime_source_manifest(path: Path) -> OnnxRuntimeSourceManifest:
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"ONNX Runtime source manifest could not be read: {path}") from error
    return OnnxRuntimeSourceManifest.model_validate(raw)


def load_tiny_onnx_fixture_manifest(path: Path) -> TinyOnnxFixtureManifest:
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"tiny ONNX fixture manifest could not be read: {path}") from error
    return TinyOnnxFixtureManifest.model_validate(raw)


def verify_tiny_onnx_fixture(
    manifest: TinyOnnxFixtureManifest,
    project_root: Path,
    *,
    storage_root: Path | None = None,
) -> list[str]:
    root = project_root.resolve()
    storage = (storage_root or root / "storage").resolve()
    fixture_root = (storage / "models" / "stt" / "fixtures" / manifest.fixture_id).resolve()
    model = (fixture_root / manifest.model_file).resolve()
    generator = (root / manifest.generator_file).resolve()
    if model.parent != fixture_root:
        return ["tiny ONNX fixture model escapes its pinned fixture root"]
    errors: list[str] = []
    if not model.is_file():
        errors.append(f"tiny ONNX fixture model not found: {model}")
    else:
        if model.stat().st_size != manifest.model_bytes:
            errors.append("tiny ONNX fixture model size mismatch")
        if sha256_file(model) != manifest.model_sha256:
            errors.append("tiny ONNX fixture model sha256 mismatch")
    if not generator.is_file():
        errors.append(f"tiny ONNX fixture generator not found: {generator}")
    elif sha256_file(generator) != manifest.generator_sha256:
        errors.append("tiny ONNX fixture generator sha256 mismatch")
    return errors


__all__ = [
    "OnnxRuntimeSourceManifest",
    "TinyOnnxFixtureManifest",
    "load_onnxruntime_source_manifest",
    "load_tiny_onnx_fixture_manifest",
    "verify_tiny_onnx_fixture",
]
