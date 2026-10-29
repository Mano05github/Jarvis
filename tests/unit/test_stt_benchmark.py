import json
import wave
from dataclasses import dataclass
from pathlib import Path

from jarvis.benchmarking.corpus import CorpusEntry, write_corpus
from jarvis.benchmarking.process import ExecutionResult
from jarvis.benchmarking.stt import benchmark_stt


@dataclass(frozen=True)
class FakeTranscription:
    hypothesis: str
    execution: ExecutionResult


class FakeAdapter:
    def transcribe(self, audio: Path, output_directory: Path) -> FakeTranscription:
        assert audio.is_file()
        output_directory.mkdir(parents=True, exist_ok=True)
        return FakeTranscription(
            hypothesis="open notepad",
            execution=ExecutionResult(
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


class FailingAdapter:
    def transcribe(self, audio: Path, output_directory: Path) -> FakeTranscription:
        raise RuntimeError("synthetic failure")


def _write_wav(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(16_000)
        audio.writeframes(b"\0\0" * 16_000)


def test_benchmark_stt_writes_results(tmp_path: Path) -> None:
    corpus_root = tmp_path / "corpus"
    audio = corpus_root / "raw/sample.wav"
    _write_wav(audio)
    manifest = corpus_root / "corpus.jsonl"
    write_corpus(
        [
            CorpusEntry(
                utterance_id="sample_001",
                language="en",
                reference="Open Notepad",
                intent_label="app.open",
                condition="quiet-near",
                split="held-out",
                audio_file="raw/sample.wav",
                consented=True,
            )
        ],
        manifest,
    )
    output = tmp_path / "output"
    summary = benchmark_stt(
        engine_id="fake",
        manifest=manifest,
        corpus_root=corpus_root,
        output_directory=output,
        adapter=FakeAdapter(),
    )
    assert summary["completed"] == 1
    assert summary["attempted"] == 1
    assert summary["missing_audio"] == 0
    assert summary["overall"]["exact_match_rate"] == 1
    assert summary["overall"]["p95_real_time_factor"] == 0.5
    assert json.loads((output / "summary.json").read_text())["engine_id"] == "fake"
    assert (output / "samples.jsonl").is_file()
    assert (output / "report.md").is_file()


def test_benchmark_stt_records_sample_failure(tmp_path: Path) -> None:
    corpus_root = tmp_path / "corpus"
    audio = corpus_root / "raw/sample.wav"
    _write_wav(audio)
    manifest = corpus_root / "corpus.jsonl"
    write_corpus(
        [
            CorpusEntry(
                utterance_id="sample_001",
                language="en",
                reference="Open Notepad",
                intent_label="app.open",
                condition="quiet-near",
                split="held-out",
                audio_file="raw/sample.wav",
                consented=True,
            )
        ],
        manifest,
    )
    summary = benchmark_stt(
        engine_id="failing",
        manifest=manifest,
        corpus_root=corpus_root,
        output_directory=tmp_path / "output",
        adapter=FailingAdapter(),
    )
    assert summary["completed"] == 0
    assert summary["failed"] == 1


def test_benchmark_stt_separates_unrecorded_audio_from_failures(tmp_path: Path) -> None:
    corpus_root = tmp_path / "corpus"
    manifest = corpus_root / "corpus.jsonl"
    write_corpus(
        [
            CorpusEntry(
                utterance_id="missing_001",
                language="en",
                reference="Open Notepad",
                intent_label="app.open",
                condition="quiet-near",
                split="development",
                audio_file="raw/missing.wav",
                consented=True,
            )
        ],
        manifest,
    )
    summary = benchmark_stt(
        engine_id="fake",
        manifest=manifest,
        corpus_root=corpus_root,
        output_directory=tmp_path / "output",
        adapter=FakeAdapter(),
    )
    assert summary["attempted"] == 0
    assert summary["completed"] == 0
    assert summary["missing_audio"] == 1
    assert summary["failed"] == 0


def test_benchmark_stt_filters_corpus_language(tmp_path: Path) -> None:
    corpus_root = tmp_path / "corpus"
    _write_wav(corpus_root / "raw/en.wav")
    _write_wav(corpus_root / "raw/ta.wav")
    manifest = corpus_root / "corpus.jsonl"
    write_corpus(
        [
            CorpusEntry(
                utterance_id=f"{language}_001",
                language=language,
                reference="Open Notepad",
                intent_label="app.open",
                condition="quiet-near",
                split="development",
                audio_file=f"raw/{language}.wav",
                consented=True,
            )
            for language in ("en", "ta")
        ],
        manifest,
    )
    summary = benchmark_stt(
        engine_id="fake",
        manifest=manifest,
        corpus_root=corpus_root,
        output_directory=tmp_path / "output",
        adapter=FakeAdapter(),
        corpus_language="ta",
    )
    assert summary["samples"] == 1
    assert summary["by_language"].keys() == {"ta"}
