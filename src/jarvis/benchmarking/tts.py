"""TTS corpus validation, execution and report generation."""

from __future__ import annotations

import json
import statistics
import wave
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from jarvis.benchmarking.process import ExecutionResult


class TTSEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"] = "1.0"
    utterance_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{2,63}$")
    language: Literal["ta", "en", "mixed"]
    text: str = Field(min_length=1, max_length=2_000)
    category: Literal["conversation", "command", "technical", "number-date"]
    split: Literal["development", "held-out"]


class Synthesis(Protocol):
    @property
    def audio_file(self) -> Path: ...

    @property
    def execution(self) -> ExecutionResult: ...


class Synthesizer(Protocol):
    def synthesize(self, entry: TTSEntry, output_directory: Path) -> Synthesis: ...


@dataclass(frozen=True, slots=True)
class TTSSampleResult:
    utterance_id: str
    language: str
    category: str
    split: str
    elapsed_seconds: float | None
    audio_seconds: float | None
    real_time_factor: float | None
    peak_rss_bytes: int | None
    cpu_seconds: float | None
    error: str | None


def load_tts_manifest(path: Path) -> list[TTSEntry]:
    entries: list[TTSEntry] = []
    identifiers: set[str] = set()
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        entry = TTSEntry.model_validate_json(line)
        if entry.utterance_id in identifiers:
            raise ValueError(f"duplicate utterance_id on line {line_number}: {entry.utterance_id}")
        identifiers.add(entry.utterance_id)
        entries.append(entry)
    if not entries:
        raise ValueError("TTS manifest is empty")
    return entries


def _wav_duration(path: Path) -> float:
    with wave.open(str(path), "rb") as audio:
        rate = audio.getframerate()
        frames = audio.getnframes()
    if rate <= 0:
        raise ValueError(f"invalid WAV sample rate: {path}")
    return frames / rate


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, round((len(ordered) - 1) * percentile)))
    return ordered[index]


def benchmark_tts(
    *,
    engine_id: str,
    manifest: Path,
    output_directory: Path,
    synthesizer: Synthesizer,
    measurement_profile: str = "cold-process-per-utterance",
    engine_metadata: Mapping[str, object] | None = None,
    language: Literal["ta", "en", "mixed"] | None = None,
    split: Literal["development", "held-out"] | None = None,
) -> dict[str, object]:
    output_directory.mkdir(parents=True, exist_ok=True)
    artifacts = output_directory / "artifacts"
    artifacts.mkdir(exist_ok=True)
    results: list[TTSSampleResult] = []

    entries = load_tts_manifest(manifest)
    if language is not None:
        entries = [entry for entry in entries if entry.language == language]
    if split is not None:
        entries = [entry for entry in entries if entry.split == split]
    if not entries:
        raise ValueError("TTS filters selected no prompts")

    for entry in entries:
        try:
            synthesis = synthesizer.synthesize(entry, artifacts / entry.utterance_id)
            duration = _wav_duration(synthesis.audio_file)
            elapsed = synthesis.execution.elapsed_seconds
            results.append(
                TTSSampleResult(
                    utterance_id=entry.utterance_id,
                    language=entry.language,
                    category=entry.category,
                    split=entry.split,
                    elapsed_seconds=elapsed,
                    audio_seconds=duration,
                    real_time_factor=elapsed / duration if duration > 0 else None,
                    peak_rss_bytes=synthesis.execution.peak_rss_bytes,
                    cpu_seconds=synthesis.execution.cpu_seconds,
                    error=None,
                )
            )
        except Exception as error:
            results.append(
                TTSSampleResult(
                    utterance_id=entry.utterance_id,
                    language=entry.language,
                    category=entry.category,
                    split=entry.split,
                    elapsed_seconds=None,
                    audio_seconds=None,
                    real_time_factor=None,
                    peak_rss_bytes=None,
                    cpu_seconds=None,
                    error=f"{type(error).__name__}: {error}",
                )
            )

    completed = [result for result in results if result.error is None]
    rtfs = [result.real_time_factor for result in completed if result.real_time_factor is not None]
    elapsed_values = [
        result.elapsed_seconds for result in completed if result.elapsed_seconds is not None
    ]
    summary: dict[str, object] = {
        "schema_version": "1.0",
        "engine_id": engine_id,
        "measurement_profile": measurement_profile,
        "generated_at": datetime.now(UTC).isoformat(),
        **(engine_metadata or {}),
        "samples": len(results),
        "completed": len(completed),
        "failed": len(results) - len(completed),
        "mean_synthesis_seconds": statistics.fmean(elapsed_values) if elapsed_values else None,
        "p95_audio_ready_seconds": _percentile(elapsed_values, 0.95),
        "p95_real_time_factor": _percentile(rtfs, 0.95),
        "peak_rss_bytes": max(
            (result.peak_rss_bytes or 0 for result in completed),
            default=0,
        ),
    }
    sample_payload = "\n".join(json.dumps(asdict(result), ensure_ascii=False) for result in results)
    (output_directory / "samples.jsonl").write_text(sample_payload + "\n", encoding="utf-8")
    (output_directory / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    report = (
        f"# TTS benchmark: {engine_id}\n\n"
        f"- Samples: {summary['samples']}\n"
        f"- Completed: {summary['completed']}\n"
        f"- Failed: {summary['failed']}\n"
        f"- Measurement profile: {summary['measurement_profile']}\n"
        f"- Mean synthesis seconds: {summary['mean_synthesis_seconds']}\n"
        f"- p95 audio-ready seconds: {summary['p95_audio_ready_seconds']}\n"
        f"- p95 real-time factor: {summary['p95_real_time_factor']}\n"
        f"- Peak RSS bytes: {summary['peak_rss_bytes']}\n"
    )
    (output_directory / "report.md").write_text(report, encoding="utf-8")
    return summary
