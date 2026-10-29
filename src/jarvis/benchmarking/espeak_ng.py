"""Emergency-fallback eSpeak NG adapter."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from jarvis.benchmarking.process import ExecutionLimits, ExecutionResult, run_bounded
from jarvis.benchmarking.tts import Synthesis, TTSEntry


@dataclass(frozen=True, slots=True)
class EspeakConfig:
    executable: Path
    voice: str = "ta"
    speed_wpm: int = 155

    def validate(self) -> None:
        if not self.executable.is_file():
            raise FileNotFoundError(f"eSpeak NG executable not found: {self.executable}")
        if not 80 <= self.speed_wpm <= 300:
            raise ValueError("speed_wpm must be between 80 and 300")


@dataclass(frozen=True, slots=True)
class EspeakSynthesis:
    audio_file: Path
    execution: ExecutionResult


def build_command(config: EspeakConfig, entry: TTSEntry, output: Path) -> tuple[str, ...]:
    return (
        str(config.executable),
        "-v",
        config.voice,
        "-s",
        str(config.speed_wpm),
        "-w",
        str(output),
        entry.text,
    )


class EspeakAdapter:
    def __init__(self, config: EspeakConfig, limits: ExecutionLimits | None = None) -> None:
        config.validate()
        self.config = config
        self.limits = limits or ExecutionLimits(timeout_seconds=30)

    def synthesize(self, entry: TTSEntry, output_directory: Path) -> Synthesis:
        output_directory.mkdir(parents=True, exist_ok=True)
        output = output_directory / f"{entry.utterance_id}.wav"
        execution = run_bounded(build_command(self.config, entry, output), limits=self.limits)
        if execution.timed_out:
            raise TimeoutError(f"eSpeak NG timed out after {execution.elapsed_seconds:.2f}s")
        if execution.exit_code != 0:
            raise RuntimeError(
                f"eSpeak NG failed with exit code {execution.exit_code}: "
                f"{execution.stderr_tail[-2000:]}"
            )
        if not output.is_file():
            raise RuntimeError(f"eSpeak NG did not create {output}")
        return EspeakSynthesis(output, execution)
