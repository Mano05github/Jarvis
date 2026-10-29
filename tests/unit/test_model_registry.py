import hashlib
import json
from pathlib import Path

from jarvis.models import ModelManifest, load_manifest, verify_model
from jarvis.storage import StorageLayout


def manifest_for(payload: bytes) -> ModelManifest:
    return ModelManifest(
        model_id="fixture",
        function="stt",
        engine="test",
        version="1",
        languages=("ta", "en"),
        source_url="https://example.com/model.bin",
        license_name="test-only",
        expected_bytes=len(payload),
        sha256=hashlib.sha256(payload).hexdigest(),
        relative_file="fixture/model.bin",
    )


def test_verify_model_accepts_matching_asset(tmp_path: Path) -> None:
    payload = b"fixture model"
    layout = StorageLayout(tmp_path / "storage")
    asset = layout.path("models", "stt", "fixture/model.bin", create_parent=True)
    asset.write_bytes(payload)
    assert verify_model(manifest_for(payload), layout) == []


def test_verify_model_reports_tampering(tmp_path: Path) -> None:
    expected = b"expected"
    layout = StorageLayout(tmp_path / "storage")
    asset = layout.path("models", "stt", "fixture/model.bin", create_parent=True)
    asset.write_bytes(b"tampered-data")
    errors = verify_model(manifest_for(expected), layout)
    assert any("size mismatch" in error for error in errors)
    assert any("sha256 mismatch" in error for error in errors)


def test_load_manifest_accepts_windows_utf8_bom(tmp_path: Path) -> None:
    manifest = manifest_for(b"fixture")
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest.model_dump(mode="json")), encoding="utf-8-sig")
    assert load_manifest(path) == manifest


def test_verify_model_reports_rejected_status(tmp_path: Path) -> None:
    payload = b"fixture model"
    layout = StorageLayout(tmp_path / "storage")
    asset = layout.path("models", "stt", "fixture/model.bin", create_parent=True)
    asset.write_bytes(payload)
    rejected = manifest_for(payload).model_copy(update={"status": "rejected"})
    assert "model status is rejected" in verify_model(rejected, layout)
