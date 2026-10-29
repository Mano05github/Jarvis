from __future__ import annotations

import json
import runpy
from pathlib import Path

import pytest
from pydantic import ValidationError

from jarvis.models.onnx_fixture import (
    OnnxRuntimeSourceManifest,
    load_onnxruntime_source_manifest,
    load_tiny_onnx_fixture_manifest,
    verify_tiny_onnx_fixture,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SOURCE = PROJECT_ROOT / "config/stt/onnxruntime-source-v1.json"
FIXTURE = PROJECT_ROOT / "config/stt/tiny-onnx-fixture-v1.json"


def payload() -> dict[str, object]:
    return json.loads(SOURCE.read_text(encoding="utf-8"))


def test_pinned_onnxruntime_source_is_official_and_canonical() -> None:
    manifest = load_onnxruntime_source_manifest(SOURCE)

    assert manifest.release_tag == "v1.31.1"
    assert manifest.source_commit == "6af1a932e2286d5c58166085d24c68783033edee"
    assert manifest.asset_bytes == 82_929_944
    assert manifest.asset_sha256 == (
        "5869e26bb25314375f2d5ef1877e3ea06b1543d6c710e6e4a1ec2f7177ab4b2c"
    )
    assert manifest.license_spdx == "MIT"
    assert len(manifest.canonical_sha256()) == 64
    assert manifest.canonical_sha256() == manifest.canonical_sha256()


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("repository_url", "https://example.com/microsoft/onnxruntime", "official"),
        ("release_tag", "main", "string_pattern_mismatch"),
        ("asset_name", "onnxruntime-win-x64-1.31.0.zip", "release tag"),
        ("asset_url", "https://example.com/runtime.zip", "official release"),
        ("license_spdx", "unknown", "literal_error"),
        ("platform", "linux-x64", "literal_error"),
        ("asset_sha256", "0" * 63, "string_pattern_mismatch"),
    ],
)
def test_source_manifest_rejects_untrusted_metadata(
    field: str, value: object, message: str
) -> None:
    candidate = payload()
    candidate[field] = value

    with pytest.raises(ValidationError, match=message):
        OnnxRuntimeSourceManifest.model_validate(candidate)


def test_source_manifest_rejects_archive_escape_and_missing_native_file() -> None:
    candidate = payload()
    members = list(candidate["required_archive_members"])
    members[0] = "../LICENSE"
    candidate["required_archive_members"] = members
    with pytest.raises(ValidationError, match="escapes"):
        OnnxRuntimeSourceManifest.model_validate(candidate)

    candidate = payload()
    candidate["required_archive_members"] = list(candidate["required_archive_members"])[:-1]
    with pytest.raises(ValidationError, match="at least 4 items"):
        OnnxRuntimeSourceManifest.model_validate(candidate)


def test_source_manifest_load_fails_closed(tmp_path: Path) -> None:
    invalid = tmp_path / "invalid.json"
    invalid.write_text("{", encoding="utf-8")
    with pytest.raises(ValueError, match="could not be read"):
        load_onnxruntime_source_manifest(invalid)


def test_tiny_fixture_is_deterministic_and_hash_bound(tmp_path: Path) -> None:
    manifest = load_tiny_onnx_fixture_manifest(FIXTURE)
    generator = runpy.run_path(str(PROJECT_ROOT / manifest.generator_file))
    model = generator["generate_model"]()
    fixture_root = tmp_path / "models/stt/fixtures" / manifest.fixture_id
    fixture_root.mkdir(parents=True)
    (fixture_root / manifest.model_file).write_bytes(model)

    assert len(model) == manifest.model_bytes
    assert manifest.expected_output == (0.0, 0.0, 1.0, 5.0)
    assert len(manifest.canonical_sha256()) == 64
    assert verify_tiny_onnx_fixture(manifest, PROJECT_ROOT, storage_root=tmp_path) == []


def test_tiny_fixture_generator_hash_normalizes_line_endings(tmp_path: Path) -> None:
    manifest = load_tiny_onnx_fixture_manifest(FIXTURE)
    source = (PROJECT_ROOT / manifest.generator_file).read_bytes()
    canonical = source.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    project_root = tmp_path / "project"
    generator = project_root / manifest.generator_file
    generator.parent.mkdir(parents=True)
    generator.write_bytes(canonical.replace(b"\n", b"\r\n"))

    loaded = runpy.run_path(str(PROJECT_ROOT / manifest.generator_file))
    fixture_root = tmp_path / "storage/models/stt/fixtures" / manifest.fixture_id
    fixture_root.mkdir(parents=True)
    (fixture_root / manifest.model_file).write_bytes(loaded["generate_model"]())

    assert (
        verify_tiny_onnx_fixture(
            manifest,
            project_root,
            storage_root=tmp_path / "storage",
        )
        == []
    )


def test_tiny_fixture_verifier_rejects_changed_model_and_generator(tmp_path: Path) -> None:
    manifest = load_tiny_onnx_fixture_manifest(FIXTURE)
    fixture_root = tmp_path / "models/stt/fixtures" / manifest.fixture_id
    fixture_root.mkdir(parents=True)
    (fixture_root / manifest.model_file).write_bytes(b"changed")

    errors = verify_tiny_onnx_fixture(manifest, PROJECT_ROOT, storage_root=tmp_path)
    assert "tiny ONNX fixture model size mismatch" in errors
    assert "tiny ONNX fixture model sha256 mismatch" in errors
