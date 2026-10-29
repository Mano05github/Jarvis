"""Quality, safety and latency benchmark for deterministic Tanglish decoding."""

from __future__ import annotations

import json
import statistics
import time
from pathlib import Path
from typing import Any

import psutil  # type: ignore[import-untyped]

from jarvis.benchmarking.qwen_semantic import SemanticDecoderCase, evidence_for_case
from jarvis.contracts.models import DecoderSource, SemanticStatusCode
from jarvis.understanding.deterministic_tanglish import decode_deterministic_tanglish
from jarvis.understanding.semantic_gate import SemanticGateError, expand_semantic_packet


def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int((len(ordered) - 1) * fraction + 0.9999)))
    return ordered[index]


def benchmark_deterministic_semantics(
    *,
    cases: list[SemanticDecoderCase],
    codebooks: dict[str, Any],
    output_directory: Path,
    repetitions: int = 100,
) -> dict[str, Any]:
    """Certify the bounded decoder against packets and the trusted semantic gate."""

    if not cases:
        raise ValueError("deterministic benchmark requires at least one case")
    if repetitions < 1:
        raise ValueError("benchmark repetitions must be positive")

    intents = {int(key): str(value) for key, value in codebooks["intents"].items()}
    references = {int(key): str(value) for key, value in codebooks["references"].items()}
    required_slots = {
        str(intent): frozenset(str(slot) for slot in slots)
        for intent, slots in codebooks["required_slots"].items()
    }
    results: list[dict[str, Any]] = []
    process = psutil.Process()
    rss_before = process.memory_info().rss

    for case in cases:
        evidence = evidence_for_case(case)
        started = time.perf_counter_ns()
        packet = decode_deterministic_tanglish(
            evidence,
            pending_operation=case.pending_operation,
            available_reference_ids=case.available_reference_ids,
        )
        elapsed_ns = time.perf_counter_ns() - started
        wire = packet.to_wire()
        error: str | None = None
        try:
            expand_semantic_packet(
                packet,
                evidence,
                intent_registry=intents,
                reference_registry=references,
                required_slots=required_slots,
                minimum_candidate_score=0.70,
                pending_operation=case.pending_operation,
                decoder_source=DecoderSource.DETERMINISTIC,
            )
            gate_valid = True
        except SemanticGateError as caught:
            gate_valid = False
            error = str(caught)
        results.append(
            {
                "case_id": case.case_id,
                "suite": case.suite,
                "packet": wire,
                "expected": case.expected.to_wire(),
                "exact_packet": wire == case.expected.to_wire(),
                "gate_valid": gate_valid,
                "safe_abstention": (
                    case.expected.status is not SemanticStatusCode.ACCEPTED
                    and packet.status is not SemanticStatusCode.ACCEPTED
                    and gate_valid
                ),
                "error": error,
                "elapsed_microseconds": elapsed_ns / 1_000,
            }
        )

    stability_outputs: set[str] = set()
    latencies: list[float] = []
    for _ in range(repetitions):
        for case in cases:
            evidence = evidence_for_case(case)
            started = time.perf_counter_ns()
            packet = decode_deterministic_tanglish(
                evidence,
                pending_operation=case.pending_operation,
                available_reference_ids=case.available_reference_ids,
            )
            latencies.append((time.perf_counter_ns() - started) / 1_000)
            stability_outputs.add(
                f"{case.case_id}:"
                + json.dumps(packet.to_wire(), sort_keys=True, separators=(",", ":"))
            )

    rss_after = process.memory_info().rss
    oracle = [item for item in results if item["suite"] == "oracle"]
    abstention = [
        item for item in results if item["expected"]["s"] != int(SemanticStatusCode.ACCEPTED)
    ]
    exact_rate = sum(bool(item["exact_packet"]) for item in results) / len(results)
    gate_rate = sum(bool(item["gate_valid"]) for item in results) / len(results)
    oracle_rate = sum(bool(item["exact_packet"]) for item in oracle) / len(oracle)
    abstention_rate = (
        sum(bool(item["safe_abstention"]) for item in abstention) / len(abstention)
        if abstention
        else None
    )
    stable = len(stability_outputs) == len(cases)
    summary: dict[str, Any] = {
        "schema_version": "1.0",
        "engine_id": "deterministic-tanglish-v1",
        "cases": len(results),
        "oracle_cases": len(oracle),
        "oracle_exact_accuracy": oracle_rate,
        "exact_packet_rate": exact_rate,
        "gate_valid_rate": gate_rate,
        "safe_abstention_rate": abstention_rate,
        "repetitions": repetitions,
        "decoder_calls": repetitions * len(cases),
        "latency_p50_microseconds": statistics.median(latencies),
        "latency_p95_microseconds": _percentile(latencies, 0.95),
        "rss_before_bytes": rss_before,
        "rss_after_bytes": rss_after,
        "rss_delta_bytes": rss_after - rss_before,
        "model_file_bytes": 0,
        "stable_outputs": stable,
        "quality_gate_pass": exact_rate == 1.0 and gate_rate == 1.0,
        "certified": exact_rate == 1.0 and gate_rate == 1.0 and stable,
    }

    output_directory.mkdir(parents=True, exist_ok=True)
    (output_directory / "results.jsonl").write_text(
        "\n".join(json.dumps(item, ensure_ascii=False, sort_keys=True) for item in results) + "\n",
        encoding="utf-8",
    )
    (output_directory / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    report = [
        "# Deterministic Tanglish semantic-decoder benchmark",
        "",
        f"- Exact packet rate: {exact_rate:.1%}",
        f"- Oracle exact accuracy: {oracle_rate:.1%}",
        f"- Deterministic-gate validity: {gate_rate:.1%}",
        "- Safe abstention: "
        + (f"{abstention_rate:.1%}" if abstention_rate is not None else "not measured"),
        f"- Median decode latency: {summary['latency_p50_microseconds']:.1f} us",
        f"- p95 decode latency: {summary['latency_p95_microseconds']:.1f} us",
        f"- Model storage: {summary['model_file_bytes']} bytes",
        f"- RSS delta: {summary['rss_delta_bytes'] / 1_048_576:.2f} MiB",
        f"- Stable outputs: {'yes' if stable else 'no'}",
        f"- Certified: {'yes' if summary['certified'] else 'no'}",
        "",
        "| Case | Suite | Exact | Gate | Safe abstention | Latency us |",
        "|---|---|---:|---:|---:|---:|",
    ]
    report.extend(
        f"| {item['case_id']} | {item['suite']} | "
        f"{'yes' if item['exact_packet'] else 'no'} | "
        f"{'yes' if item['gate_valid'] else 'no'} | "
        f"{'yes' if item['safe_abstention'] else 'no'} | "
        f"{item['elapsed_microseconds']:.1f} |"
        for item in results
    )
    (output_directory / "report.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    return summary


__all__ = ["benchmark_deterministic_semantics"]
