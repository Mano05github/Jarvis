from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType


def load_conversion_tool() -> ModuleType:
    path = Path(__file__).parents[2] / "tools" / "convert_tamil_whisper.py"
    spec = importlib.util.spec_from_file_location("convert_tamil_whisper", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_runtime_sidecars_do_not_overwrite_ctranslate2_config() -> None:
    module = load_conversion_tool()

    assert "tokenizer.json" in module.RUNTIME_SIDECARS
    assert "preprocessor_config.json" in module.RUNTIME_SIDECARS
    assert "config.json" not in module.RUNTIME_SIDECARS


def test_converter_accepts_a_pinned_safetensors_weight() -> None:
    module = load_conversion_tool()

    arguments = module.build_parser().parse_args(
        [
            "--source",
            "source",
            "--output",
            "output",
            "--storage-root",
            "storage",
            "--weight-file",
            "model.safetensors",
            "--expected-weight-sha256",
            "0" * 64,
        ]
    )

    assert arguments.weight_file == "model.safetensors"


def test_missing_optional_package_is_omitted(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    module = load_conversion_tool()

    def version(name: str) -> str:
        if name == "pip":
            raise module.importlib.metadata.PackageNotFoundError(name)
        return "1.2.3"

    monkeypatch.setattr(module.importlib.metadata, "version", version)

    assert module.installed_package_versions(("torch", "pip")) == {"torch": "1.2.3"}


def test_cleanup_removes_only_matching_partial_directories(tmp_path: Path) -> None:
    module = load_conversion_tool()
    output = tmp_path / "candidate-int8"
    stale = tmp_path / "candidate-int8.partial-deadbeef"
    unrelated = tmp_path / "different.partial-deadbeef"
    output.mkdir()
    stale.mkdir()
    unrelated.mkdir()
    (stale / "model.bin").write_bytes(b"incomplete")

    assert module.cleanup_stale_partials(output) == 1
    assert not stale.exists()
    assert unrelated.is_dir()
