"""End-to-end STT corpus execution and report generation."""

from __future__ import annotations

import json
import statistics
import wave
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, Protocol

from jarvis.benchmarking.corpus import CorpusEntry, load_corpus
from jarvis.benchmarking.metrics import char_error_rate, exact_match, word_error_rate
from jarvis.benchmarking.process import ExecutionResult


class Transcription(Protocol):
    @property
    def hypothesis(self) -> str: ...

    @property
    def execution(self) -> ExecutionResult: ...


class Transcriber(Protocol):
    def transcribe(self, audio: Path, output_directory: Path) -> Transcription: ...


@dataclass(frozen=True, slots=True)
class STTSampleResult:
    utterance_id: str
    outcome: Literal["completed", "missing_audio", "failed"]
    language: str
    condition: str
    split: str
    reference: str
    hypothesis: str | None
    audio_seconds: float | None
    elapsed_seconds: float | None
    real_time_factor: float | None
    peak_rss_bytes: int | None
    cpu_seconds: float | None
    word_error_rate: float | None
    char_error_rate: float | None
    exact_match: bool | None
    error: str | None


def wav_duration_seconds(path: Path) -> float:
    with wave.open(str(path), "rb") as audio:
        frames = audio.getnframes()
        rate = audio.getframerate()
    if rate <= 0:
        raise ValueError(f"invalid WAV sample rate: {path}")
    return frames / rate


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, round((len(ordered) - 1) * percentile)))
    return ordered[index]


def _audio_path(corpus_root: Path, entry: CorpusEntry) -> Path:
    root = corpus_root.resolve()
    candidate = root.joinpath(entry.audio_file).resolve()
    if not candidate.is_relative_to(root):
        raise ValueError(f"audio path escapes corpus root: {entry.audio_file}")
    return candidate


def _run_sample(
    entry: CorpusEntry,
    corpus_root: Path,
    artifacts: Path,
    adapter: Transcriber,
) -> STTSampleResult:
    audio = _audio_path(corpus_root, entry)
    if not audio.is_file():
        return STTSampleResult(
            utterance_id=entry.utterance_id,
            outcome="missing_audio",
            language=entry.language,
            condition=entry.condition,
            split=entry.split,
            reference=entry.reference,
            hypothesis=None,
            audio_seconds=None,
            elapsed_seconds=None,
            real_time_factor=None,
            peak_rss_bytes=None,
            cpu_seconds=None,
            word_error_rate=None,
            char_error_rate=None,
            exact_match=None,
            error=None,
        )
    try:
        duration = wav_duration_seconds(audio)
        transcription = adapter.transcribe(audio, artifacts / entry.utterance_id)
        elapsed = transcription.execution.elapsed_seconds
        hypothesis = transcription.hypothesis
        return STTSampleResult(
            utterance_id=entry.utterance_id,
            outcome="completed",
            language=entry.language,
            condition=entry.condition,
            split=entry.split,
            reference=entry.reference,
            hypothesis=hypothesis,
            audio_seconds=duration,
            elapsed_seconds=elapsed,
            real_time_factor=elapsed / duration if duration > 0 else None,
            peak_rss_bytes=transcription.execution.peak_rss_bytes,
            cpu_seconds=transcription.execution.cpu_seconds,
            word_error_rate=word_error_rate(entry.reference, hypothesis),
            char_error_rate=char_error_rate(entry.reference, hypothesis),
            exact_match=exact_match(entry.reference, hypothesis),
            error=None,
        )
    except Exception as error:
        return STTSampleResult(
            utterance_id=entry.utterance_id,
            outcome="failed",
            language=entry.language,
            condition=entry.condition,
            split=entry.split,
            reference=entry.reference,
            hypothesis=None,
            audio_seconds=None,
            elapsed_seconds=None,
            real_time_factor=None,
            peak_rss_bytes=None,
            cpu_seconds=None,
            word_error_rate=None,
            char_error_rate=None,
            exact_match=None,
            error=f"{type(error).__name__}: {error}",
        )


def summarize_results(results: list[STTSampleResult]) -> dict[str, object]:
    completed = [result for result in results if result.outcome == "completed"]
    missing = [result for result in results if result.outcome == "missing_audio"]
    failed = [result for result in results if result.outcome == "failed"]
    by_language: dict[str, list[STTSampleResult]] = defaultdict(list)
    for result in completed:
        by_language[result.language].append(result)

    def metrics(items: list[STTSampleResult]) -> dict[str, object]:
        wers = [item.word_error_rate for item in items if item.word_error_rate is not None]
        cers = [item.char_error_rate for item in items if item.char_error_rate is not None]
        rtfs = [item.real_time_factor for item in items if item.real_time_factor is not None]
        return {
            "samples": len(items),
            "exact_match_rate": (
                sum(item.exact_match is True for item in items) / len(items) if items else None
            ),
            "mean_wer": statistics.fmean(wers) if wers else None,
            "mean_cer": statistics.fmean(cers) if cers else None,
            "p95_real_time_factor": _percentile(rtfs, 0.95),
            "peak_rss_bytes": max(
                (item.peak_rss_bytes or 0 for item in items),
                default=0,
            ),
        }

    return {
        "samples": len(results),
        "attempted": len(completed) + len(failed),
        "completed": len(completed),
        "missing_audio": len(missing),
        "failed": len(failed),
        "overall": metrics(completed),
        "by_language": {language: metrics(items) for language, items in by_language.items()},
    }


def _markdown_report(engine_id: str, summary: dict[str, object]) -> str:
    overall = summary["overall"]
    assert isinstance(overall, dict)
    lines = [
        f"# STT benchmark: {engine_id}",
        "",
        f"Generated: {datetime.now(UTC).isoformat()}",
        "",
        f"- Samples: {summary['samples']}",
        f"- Attempted: {summary['attempted']}",
        f"- Completed: {summary['completed']}",
        f"- Not recorded: {summary['missing_audio']}",
        f"- Failed: {summary['failed']}",
        f"- Exact match: {overall.get('exact_match_rate')}",
        f"- Mean WER: {overall.get('mean_wer')}",
        f"- Mean CER: {overall.get('mean_cer')}",
        f"- p95 real-time factor: {overall.get('p95_real_time_factor')}",
        f"- Peak RSS bytes: {overall.get('peak_rss_bytes')}",
        "",
        "Machine-readable details are in `summary.json` and `samples.jsonl`.",
        "",
    ]
    return "\n".join(lines)


def benchmark_stt(
    *,
    engine_id: str,
    manifest: Path,
    corpus_root: Path,
    output_directory: Path,
    adapter: Transcriber,
    measurement_profile: str = "cold-process-per-utterance",
    engine_metadata: Mapping[str, object] | None = None,
    corpus_language: str | None = None,
) -> dict[str, object]:
    entries = load_corpus(manifest)
    if corpus_language is not None:
        entries = [entry for entry in entries if entry.language == corpus_language]
    output_directory.mkdir(parents=True, exist_ok=True)
    artifacts = output_directory / "artifacts"
    artifacts.mkdir(exist_ok=True)

    results = [_run_sample(entry, corpus_root, artifacts, adapter) for entry in entries]
    summary = {
        "schema_version": "1.0",
        "engine_id": engine_id,
        "measurement_profile": measurement_profile,
        "generated_at": datetime.now(UTC).isoformat(),
        **(engine_metadata or {}),
        **summarize_results(results),
    }
    samples = "\n".join(json.dumps(asdict(result), ensure_ascii=False) for result in results)
    (output_directory / "samples.jsonl").write_text(samples + "\n", encoding="utf-8")
    (output_directory / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (output_directory / "report.md").write_text(
        _markdown_report(engine_id, summary),
        encoding="utf-8",
    )
    return summary
