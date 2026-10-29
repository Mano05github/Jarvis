"""Privacy-safe single-file STT engine smoke test."""

from __future__ import annotations

import hashlib
from pathlib import Path

from jarvis.benchmarking.stt import Transcriber, wav_duration_seconds


def smoke_stt(adapter: Transcriber, audio: Path, output_directory: Path) -> dict[str, object]:
    duration = wav_duration_seconds(audio)
    result = adapter.transcribe(audio, output_directory / "artifacts")
    transcript_hash = hashlib.sha256(result.hypothesis.encode("utf-8")).hexdigest()
    return {
        "schema_version": "1.0",
        "status": "passed",
        "audio_seconds": duration,
        "elapsed_seconds": result.execution.elapsed_seconds,
        "real_time_factor": result.execution.elapsed_seconds / duration,
        "peak_rss_bytes": result.execution.peak_rss_bytes,
        "cpu_seconds": result.execution.cpu_seconds,
        "transcript_characters": len(result.hypothesis),
        "transcript_sha256": transcript_hash,
    }
