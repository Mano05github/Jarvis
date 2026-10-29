import json
import wave
from dataclasses import dataclass
from pathlib import Path

from jarvis.benchmarking.process import ExecutionResult
from jarvis.benchmarking.tts import TTSEntry, benchmark_tts


@dataclass(frozen=True)
class FakeSynthesis:
    audio_file: Path
    execution: ExecutionResult


class FakeSynthesizer:
    def synthesize(self, entry: TTSEntry, output_directory: Path) -> FakeSynthesis:
        output_directory.mkdir(parents=True, exist_ok=True)
        output = output_directory / f"{entry.utterance_id}.wav"
        with wave.open(str(output), "wb") as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(16_000)
            audio.writeframes(b"\0\0" * 32_000)
        return FakeSynthesis(
            output,
            ExecutionResult(
                args=("fake",),
                exit_code=0,
                timed_out=False,
                elapsed_seconds=0.5,
                peak_rss_bytes=200,
                cpu_seconds=0.2,
                stdout_tail="",
                stderr_tail="",
                output_truncated=False,
            ),
        )


class FailingSynthesizer:
    def synthesize(self, entry: TTSEntry, output_directory: Path) -> FakeSynthesis:
        raise RuntimeError("synthetic failure")


def test_benchmark_tts_writes_report(tmp_path: Path) -> None:
    manifest = tmp_path / "tts.jsonl"
    manifest.write_text(
        TTSEntry(
            utterance_id="ta_sample_001",
            language="ta",
            text="வணக்கம்",
            category="conversation",
            split="held-out",
        ).model_dump_json()
        + "\n",
        encoding="utf-8",
    )
    output = tmp_path / "results"
    summary = benchmark_tts(
        engine_id="fake",
        manifest=manifest,
        output_directory=output,
        synthesizer=FakeSynthesizer(),
    )
    assert summary["completed"] == 1
    assert summary["p95_real_time_factor"] == 0.25
    assert summary["p95_audio_ready_seconds"] == 0.5
    assert summary["measurement_profile"] == "cold-process-per-utterance"
    assert json.loads((output / "summary.json").read_text())["engine_id"] == "fake"


def test_benchmark_tts_records_failure(tmp_path: Path) -> None:
    manifest = tmp_path / "tts.jsonl"
    manifest.write_text(
        TTSEntry(
            utterance_id="ta_sample_001",
            language="ta",
            text="வணக்கம்",
            category="conversation",
            split="held-out",
        ).model_dump_json()
        + "\n",
        encoding="utf-8",
    )
    summary = benchmark_tts(
        engine_id="failing",
        manifest=manifest,
        output_directory=tmp_path / "results",
        synthesizer=FailingSynthesizer(),
    )
    assert summary["completed"] == 0
    assert summary["failed"] == 1


def test_benchmark_tts_filters_without_exposing_held_out_prompts(tmp_path: Path) -> None:
    manifest = tmp_path / "tts.jsonl"
    entries = (
        TTSEntry(
            utterance_id="ta_dev_001",
            language="ta",
            text="வணக்கம்",
            category="conversation",
            split="development",
        ),
        TTSEntry(
            utterance_id="ta_held_001",
            language="ta",
            text="நன்றி",
            category="conversation",
            split="held-out",
        ),
    )
    manifest.write_text(
        "\n".join(entry.model_dump_json() for entry in entries) + "\n", encoding="utf-8"
    )

    summary = benchmark_tts(
        engine_id="fake",
        manifest=manifest,
        output_directory=tmp_path / "results",
        synthesizer=FakeSynthesizer(),
        language="ta",
        split="development",
    )

    assert summary["samples"] == 1
    samples = (tmp_path / "results" / "samples.jsonl").read_text(encoding="utf-8")
    assert "ta_dev_001" in samples
    assert "ta_held_001" not in samples
