from __future__ import annotations

import json
from pathlib import Path

from jarvis.benchmarking.deterministic_semantic import (
    benchmark_deterministic_semantics,
)
from jarvis.benchmarking.qwen_semantic import load_decoder_cases

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_ROOT = PROJECT_ROOT / "config" / "semantic-decoder"


def test_deterministic_benchmark_certifies_complete_case_pack(tmp_path: Path) -> None:
    summary = benchmark_deterministic_semantics(
        cases=load_decoder_cases(CONFIG_ROOT / "benchmark-v1.jsonl"),
        codebooks=json.loads((CONFIG_ROOT / "codebooks-v1.json").read_text(encoding="utf-8")),
        output_directory=tmp_path,
        repetitions=2,
    )

    assert summary["exact_packet_rate"] == 1.0
    assert summary["gate_valid_rate"] == 1.0
    assert summary["model_file_bytes"] == 0
    assert summary["certified"] is True
    assert (tmp_path / "results.jsonl").is_file()
    assert (tmp_path / "summary.json").is_file()
    assert (tmp_path / "report.md").is_file()
