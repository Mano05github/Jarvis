import json
from pathlib import Path

import pytest

from jarvis.benchmarking.process import ExecutionResult
from jarvis.benchmarking.whisper_cpp import (
    WhisperCppAdapter,
    WhisperCppConfig,
    _extract_text,
    build_command,
)


def test_build_command_uses_structured_json_output(tmp_path: Path) -> None:
    config = WhisperCppConfig(tmp_path / "whisper.exe", tmp_path / "model.bin", threads=3)
    command = build_command(config, tmp_path / "audio.wav", tmp_path / "output")
    assert command[0] == str(config.executable)
    assert command[command.index("-t") + 1] == "3"
    assert "-oj" in command


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({"text": " hello "}, "hello"),
        ({"transcription": [{"text": "hello"}, {"text": "world"}]}, "hello world"),
        ({"segments": [{"text": "வணக்கம்"}]}, "வணக்கம்"),
    ],
)
def test_extract_text(payload: object, expected: str) -> None:
    assert _extract_text(payload) == expected


def test_extract_text_rejects_unknown_schema() -> None:
    with pytest.raises(ValueError, match="transcript text"):
        _extract_text({"unexpected": []})


def _execution(*, exit_code: int = 0, timed_out: bool = False) -> ExecutionResult:
    return ExecutionResult(
        args=("whisper",),
        exit_code=exit_code,
        timed_out=timed_out,
        elapsed_seconds=0.5,
        peak_rss_bytes=100,
        cpu_seconds=0.25,
        stdout_tail="",
        stderr_tail="failure detail",
        output_truncated=False,
    )


def _adapter(tmp_path: Path) -> WhisperCppAdapter:
    executable = tmp_path / "whisper.exe"
    model = tmp_path / "model.bin"
    executable.touch()
    model.touch()
    return WhisperCppAdapter(WhisperCppConfig(executable, model))


def test_config_validation(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="executable"):
        WhisperCppConfig(tmp_path / "missing.exe", tmp_path / "missing.bin").validate()
    executable = tmp_path / "whisper.exe"
    executable.touch()
    with pytest.raises(FileNotFoundError, match="model"):
        WhisperCppConfig(executable, tmp_path / "missing.bin").validate()
    model = tmp_path / "model.bin"
    model.touch()
    with pytest.raises(ValueError, match="threads"):
        WhisperCppConfig(executable, model, threads=9).validate()


def test_adapter_reads_structured_output(monkeypatch, tmp_path: Path) -> None:
    adapter = _adapter(tmp_path)
    audio = tmp_path / "sample.with.dot.wav"
    audio.touch()

    def fake_run(args, *, limits):
        prefix = Path(args[args.index("-of") + 1])
        Path(f"{prefix}.json").write_text(
            json.dumps({"transcription": [{"text": "hello"}]}),
            encoding="utf-8",
        )
        return _execution()

    monkeypatch.setattr("jarvis.benchmarking.whisper_cpp.run_bounded", fake_run)
    result = adapter.transcribe(audio, tmp_path / "output")
    assert result.hypothesis == "hello"


@pytest.mark.parametrize(
    ("execution", "error"),
    [
        (_execution(timed_out=True), TimeoutError),
        (_execution(exit_code=2), RuntimeError),
    ],
)
def test_adapter_reports_execution_failures(
    monkeypatch,
    tmp_path: Path,
    execution: ExecutionResult,
    error: type[Exception],
) -> None:
    adapter = _adapter(tmp_path)
    audio = tmp_path / "sample.wav"
    audio.touch()
    monkeypatch.setattr(
        "jarvis.benchmarking.whisper_cpp.run_bounded",
        lambda args, *, limits: execution,
    )
    with pytest.raises(error):
        adapter.transcribe(audio, tmp_path / "output")


def test_adapter_requires_json_output(monkeypatch, tmp_path: Path) -> None:
    adapter = _adapter(tmp_path)
    audio = tmp_path / "sample.wav"
    audio.touch()
    monkeypatch.setattr(
        "jarvis.benchmarking.whisper_cpp.run_bounded",
        lambda args, *, limits: _execution(),
    )
    with pytest.raises(RuntimeError, match="did not create"):
        adapter.transcribe(audio, tmp_path / "output")
