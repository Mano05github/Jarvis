import wave
from dataclasses import dataclass
from pathlib import Path

from jarvis.benchmarking.process import ExecutionResult
from jarvis.benchmarking.smoke import smoke_stt


@dataclass(frozen=True)
class FakeTranscription:
    hypothesis: str
    execution: ExecutionResult


class FakeAdapter:
    def transcribe(self, audio: Path, output_directory: Path) -> FakeTranscription:
        return FakeTranscription(
            "private transcript",
            ExecutionResult(
                args=("fake",),
                exit_code=0,
                timed_out=False,
                elapsed_seconds=0.5,
                peak_rss_bytes=100,
                cpu_seconds=0.25,
                stdout_tail="",
                stderr_tail="",
                output_truncated=False,
            ),
        )


def test_smoke_summary_omits_transcript(tmp_path: Path) -> None:
    audio_path = tmp_path / "sample.wav"
    with wave.open(str(audio_path), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(16_000)
        audio.writeframes(b"\0\0" * 16_000)
    summary = smoke_stt(FakeAdapter(), audio_path, tmp_path / "output")
    assert summary["status"] == "passed"
    assert summary["real_time_factor"] == 0.5
    assert "transcript" not in summary
    assert "transcript_sha256" in summary
