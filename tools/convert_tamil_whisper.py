"""Convert a pinned Whisper model to a project-local CTranslate2 INT8 model."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import shutil
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

# CTranslate2 writes its own config.json into the converted model directory.
# Copying the Hugging Face config.json there first makes ModelSpec.save fail.
RUNTIME_SIDECARS = (
    "tokenizer.json",
    "preprocessor_config.json",
    "generation_config.json",
    "normalizer.json",
)


def installed_package_versions(names: tuple[str, ...]) -> dict[str, str]:
    versions: dict[str, str] = {}
    for name in names:
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            # uv-managed virtual environments do not need to contain pip.
            continue
    return versions


def cleanup_stale_partials(output: Path) -> int:
    """Remove only invalid sibling directories created by interrupted conversions."""
    removed = 0
    prefix = f"{output.name}.partial-"
    for candidate in output.parent.iterdir():
        if candidate.is_dir() and candidate.name.startswith(prefix):
            validated = within(candidate, output.parent)
            shutil.rmtree(validated)
            removed += 1
    return removed


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def within(path: Path, root: Path) -> Path:
    resolved = path.resolve()
    if not resolved.is_relative_to(root.resolve()):
        raise ValueError(f"path must remain under {root.resolve()}: {resolved}")
    return resolved


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--storage-root", type=Path, required=True)
    parser.add_argument("--weight-file", default="pytorch_model.bin")
    parser.add_argument("--expected-weight-sha256", required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    storage = args.storage_root.resolve()
    source = within(args.source, storage)
    output = within(args.output, storage)
    weight_relative = Path(args.weight_file)
    if weight_relative.is_absolute() or ".." in weight_relative.parts:
        raise ValueError("weight file must be relative to the source model")
    weight = source / weight_relative
    if not weight.is_file():
        raise FileNotFoundError(f"model weight is missing: {weight}")
    actual_hash = sha256_file(weight)
    if actual_hash != args.expected_weight_sha256.casefold():
        raise ValueError("pinned PyTorch weight SHA-256 mismatch")
    manifest_path = output / "jarvis-conversion-manifest.json"
    if manifest_path.is_file() and (output / "model.bin").is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("source_weight_sha256") == actual_hash:
            cleanup_stale_partials(output)
            print(json.dumps(manifest, indent=2))
            return 0
        raise ValueError("existing conversion does not match the pinned source")
    if output.exists():
        raise FileExistsError(f"incomplete output already exists: {output}")

    from ctranslate2.converters import TransformersConverter
    from transformers import WhisperProcessor

    temp_parent = within(storage / "temp", storage)
    temp_parent.mkdir(parents=True, exist_ok=True)
    partial = output.with_name(f"{output.name}.partial-{uuid4().hex}")
    partial.parent.mkdir(parents=True, exist_ok=True)
    try:
        with tempfile.TemporaryDirectory(dir=temp_parent) as temporary:
            staging = Path(temporary) / "source"
            shutil.copytree(source, staging)
            processor = WhisperProcessor.from_pretrained(staging, local_files_only=True)
            processor.save_pretrained(staging)
            copy_files = [name for name in RUNTIME_SIDECARS if (staging / name).is_file()]
            converter = TransformersConverter(str(staging), copy_files=copy_files)
            converter.convert(str(partial), quantization="int8", force=False)
        required = (partial / "model.bin", partial / "config.json")
        if not all(path.is_file() for path in required):
            raise RuntimeError("CTranslate2 conversion did not create the required files")
        files = [
            {
                "name": str(path.relative_to(partial)).replace("\\", "/"),
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
            for path in sorted(partial.rglob("*"))
            if path.is_file()
        ]
        manifest = {
            "schema_version": "1.0",
            "created_at": datetime.now(UTC).isoformat(),
            "source": str(source.relative_to(storage)).replace("\\", "/"),
            "source_weight_sha256": actual_hash,
            "source_weight_file": weight_relative.as_posix(),
            "quantization": "int8",
            "python": sys.version.split()[0],
            "packages": installed_package_versions(
                ("ctranslate2", "faster-whisper", "pip", "torch", "transformers")
            ),
            "files": files,
        }
        (partial / "jarvis-conversion-manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        partial.replace(output)
    except BaseException:
        # Any failed stage can leave hundreds of MB in this unique directory.
        # It is never a valid model until the final atomic rename succeeds.
        shutil.rmtree(partial, ignore_errors=True)
        raise
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
