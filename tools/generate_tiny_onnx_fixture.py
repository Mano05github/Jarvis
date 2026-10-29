"""Generate Jarvis's dependency-free deterministic ONNX fixture.

This is developer tooling only. It implements the small subset of protobuf wire
encoding required by the audited graph and does not enter the Jarvis runtime.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
from pathlib import Path

SCHEMA_VERSION = "1.0"
FIXTURE_ID = "tiny-affine-relu-v1"
ONNX_SCHEMA_TAG = "v1.22.0"
ONNX_RUNTIME_DEPENDENCY_HASH = "2b2cd58ac7a26df5371266149e0c76776330cdf1"
IR_VERSION = 8
OPSET_VERSION = 17
TENSOR_FLOAT = 1
SHAPE = (1, 4)
INPUT = (-2.0, -1.0, 0.0, 2.0)
EXPECTED = (0.0, 0.0, 1.0, 5.0)


def _varint(value: int) -> bytes:
    if value < 0:
        raise ValueError("fixture encoder supports only non-negative varints")
    encoded = bytearray()
    while value >= 0x80:
        encoded.append((value & 0x7F) | 0x80)
        value >>= 7
    encoded.append(value)
    return bytes(encoded)


def _key(field_number: int, wire_type: int) -> bytes:
    return _varint((field_number << 3) | wire_type)


def _integer(field_number: int, value: int) -> bytes:
    return _key(field_number, 0) + _varint(value)


def _blob(field_number: int, value: bytes) -> bytes:
    return _key(field_number, 2) + _varint(len(value)) + value


def _text(field_number: int, value: str) -> bytes:
    return _blob(field_number, value.encode("utf-8"))


def _message(field_number: int, value: bytes) -> bytes:
    return _blob(field_number, value)


def _dimension(value: int) -> bytes:
    return _integer(1, value)


def _shape(dimensions: tuple[int, ...]) -> bytes:
    return b"".join(_message(1, _dimension(value)) for value in dimensions)


def _tensor_type(dimensions: tuple[int, ...]) -> bytes:
    tensor = _integer(1, TENSOR_FLOAT) + _message(2, _shape(dimensions))
    return _message(1, tensor)


def _value_info(name: str, dimensions: tuple[int, ...]) -> bytes:
    return _text(1, name) + _message(2, _tensor_type(dimensions))


def _float_tensor(name: str, values: tuple[float, ...]) -> bytes:
    packed_dimensions = b"".join(_varint(value) for value in SHAPE)
    raw_data = struct.pack(f"<{len(values)}f", *values)
    return (
        _blob(1, packed_dimensions)
        + _integer(2, TENSOR_FLOAT)
        + _text(8, name)
        + _blob(9, raw_data)
    )


def _node(name: str, operation: str, inputs: tuple[str, ...], output: str) -> bytes:
    return (
        b"".join(_text(1, value) for value in inputs)
        + _text(2, output)
        + _text(3, name)
        + _text(4, operation)
    )


def generate_model() -> bytes:
    two = (2.0, 2.0, 2.0, 2.0)
    one = (1.0, 1.0, 1.0, 1.0)
    graph = b"".join(
        (
            _message(1, _node("scale", "Mul", ("x", "two"), "scaled")),
            _message(1, _node("bias", "Add", ("scaled", "one"), "shifted")),
            _message(1, _node("activate", "Relu", ("shifted",), "y")),
            _text(2, "jarvis_tiny_affine_relu"),
            _message(5, _float_tensor("two", two)),
            _message(5, _float_tensor("one", one)),
            _message(11, _value_info("x", SHAPE)),
            _message(12, _value_info("y", SHAPE)),
        )
    )
    operator_set = _integer(2, OPSET_VERSION)
    return b"".join(
        (
            _integer(1, IR_VERSION),
            _text(2, "jarvis-audited-wire-generator"),
            _text(3, "1.0"),
            _text(4, "ai.jarvis.fixture"),
            _integer(5, 1),
            _message(7, graph),
            _message(8, operator_set),
        )
    )


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _manifest(model: bytes, generator_path: Path) -> dict[str, object]:
    return {
        "schema_version": SCHEMA_VERSION,
        "fixture_id": FIXTURE_ID,
        "formula": "y = Relu((x * 2) + 1)",
        "onnx_schema_tag": ONNX_SCHEMA_TAG,
        "onnx_runtime_dependency_hash": ONNX_RUNTIME_DEPENDENCY_HASH,
        "ir_version": IR_VERSION,
        "opset_version": OPSET_VERSION,
        "input_name": "x",
        "input_type": "float32",
        "input_shape": list(SHAPE),
        "input_values": list(INPUT),
        "output_name": "y",
        "output_type": "float32",
        "output_shape": list(SHAPE),
        "expected_output": list(EXPECTED),
        "model_file": "model.onnx",
        "model_bytes": len(model),
        "model_sha256": _sha256(model),
        "generator_file": "tools/generate_tiny_onnx_fixture.py",
        "generator_sha256": _sha256(generator_path.read_bytes()),
        "external_data": False,
        "custom_operators": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--verify", action="store_true")
    arguments = parser.parse_args()
    model = generate_model()
    output = arguments.output.resolve()
    manifest_path = output.with_name("fixture-manifest.json")
    manifest = _manifest(model, Path(__file__).resolve())
    encoded_manifest = (
        json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=True) + "\n"
    ).encode("utf-8")
    if arguments.verify:
        if not output.is_file() or output.read_bytes() != model:
            raise SystemExit("fixture model differs from deterministic generator output")
        if not manifest_path.is_file() or manifest_path.read_bytes() != encoded_manifest:
            raise SystemExit("fixture manifest differs from deterministic generator output")
        print(f"verified {output} sha256={manifest['model_sha256']}")
        return 0
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(model)
    manifest_path.write_bytes(encoded_manifest)
    print(f"generated {output} bytes={len(model)} sha256={manifest['model_sha256']}")
    print(f"manifest {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
