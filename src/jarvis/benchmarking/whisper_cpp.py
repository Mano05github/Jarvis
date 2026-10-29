"""whisper.cpp command adapter with structured-output parsing."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from jarvis.benchmarking.process import ExecutionLimits, ExecutionResult, run_bounded
from jarvis.benchmarking.stt import Transcription


@dataclass(frozen=True, slots=True)
class WhisperCppConfig:
    executable: Path
    model: Path
    threads: int = 4
    language: str = "auto"

    def validate(self) -> None:
        if not self.executable.is_file():
            raise FileNotFoundError(f"whisper.cpp executable not found: {self.executable}")
        if not self.model.is_file():
            raise FileNotFoundError(f"whisper.cpp model not found: {self.model}")
        if not 1 <= self.threads <= 8:
            raise ValueError("threads must be between 1 and 8 on the certified target")


@dataclass(frozen=True, slots=True)
class TranscriptionResult:
    hypothesis: str
    execution: ExecutionResult
    structured_output: Path


def build_command(config: WhisperCppConfig, audio: Path, output_prefix: Path) -> tuple[str, ...]:
    return (
        str(config.executable),
        "-m",
        str(config.model),
        "-f",
        str(audio),
        "-t",
        str(config.threads),
        "-l",
        config.language,
        "-oj",
        "-of",
        str(output_prefix),
    )


def _extract_text(payload: object) -> str:
    if not isinstance(payload, dict):
        raise ValueError("whisper.cpp JSON root must be an object")
    direct = payload.get("text")
    if isinstance(direct, str):
        return direct.strip()
    for key in ("transcription", "segments"):
        segments = payload.get(key)
        if isinstance(segments, list):
            texts = [item.get("text", "") for item in segments if isinstance(item, dict)]
            return " ".join(str(text).strip() for text in texts if str(text).strip()).strip()
    raise ValueError("whisper.cpp JSON did not contain transcript text")


class WhisperCppAdapter:
    def __init__(self, config: WhisperCppConfig, limits: ExecutionLimits | None = None) -> None:
        config.validate()
        self.config = config
        self.limits = limits or ExecutionLimits()

    def transcribe(self, audio: Path, output_directory: Path) -> Transcription:
        if not audio.is_file():
            raise FileNotFoundError(f"audio file not found: {audio}")
        output_directory.mkdir(parents=True, exist_ok=True)
        prefix = output_directory / audio.stem
        execution = run_bounded(build_command(self.config, audio, prefix), limits=self.limits)
        if execution.timed_out:
            raise TimeoutError(f"whisper.cpp timed out after {execution.elapsed_seconds:.2f}s")
        if execution.exit_code != 0:
            raise RuntimeError(
                f"whisper.cpp failed with exit code {execution.exit_code}: "
                f"{execution.stderr_tail[-2000:]}"
            )
        structured_output = Path(f"{prefix}.json")
        if not structured_output.is_file():
            raise RuntimeError(f"whisper.cpp did not create {structured_output}")
        payload = json.loads(structured_output.read_text(encoding="utf-8-sig"))
        return TranscriptionResult(_extract_text(payload), execution, structured_output)
