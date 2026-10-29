from pathlib import Path

import pytest

from jarvis.benchmarking.espeak_ng import EspeakAdapter, EspeakConfig, build_command
from jarvis.benchmarking.process import ExecutionResult
from jarvis.benchmarking.tts import TTSEntry


def _entry() -> TTSEntry:
    return TTSEntry(
        utterance_id="ta_sample_001",
        language="ta",
        text="வணக்கம்",
        category="conversation",
        split="development",
    )


def _execution(*, exit_code: int = 0, timed_out: bool = False) -> ExecutionResult:
    return ExecutionResult(
        args=("espeak-ng",),
        exit_code=exit_code,
        timed_out=timed_out,
        elapsed_seconds=0.2,
        peak_rss_bytes=100,
        cpu_seconds=0.1,
        stdout_tail="",
        stderr_tail="failure detail",
        output_truncated=False,
    )


def _adapter(tmp_path: Path) -> EspeakAdapter:
    executable = tmp_path / "espeak-ng.exe"
    executable.touch()
    return EspeakAdapter(EspeakConfig(executable))


def test_espeak_config_and_command(tmp_path: Path) -> None:
    executable = tmp_path / "espeak-ng.exe"
    executable.touch()
    config = EspeakConfig(executable, voice="ta", speed_wpm=160)
    config.validate()
    command = build_command(config, _entry(), tmp_path / "result.wav")
    assert command[command.index("-v") + 1] == "ta"
    assert command[command.index("-s") + 1] == "160"
    with pytest.raises(ValueError, match="speed_wpm"):
        EspeakConfig(executable, speed_wpm=301).validate()


def test_espeak_adapter_success(monkeypatch, tmp_path: Path) -> None:
    adapter = _adapter(tmp_path)

    def fake_run(args, *, limits):
        Path(args[args.index("-w") + 1]).write_bytes(b"wav")
        return _execution()

    monkeypatch.setattr("jarvis.benchmarking.espeak_ng.run_bounded", fake_run)
    result = adapter.synthesize(_entry(), tmp_path / "output")
    assert result.audio_file.is_file()


@pytest.mark.parametrize(
    ("execution", "error"),
    [
        (_execution(timed_out=True), TimeoutError),
        (_execution(exit_code=2), RuntimeError),
    ],
)
def test_espeak_adapter_execution_errors(
    monkeypatch,
    tmp_path: Path,
    execution: ExecutionResult,
    error: type[Exception],
) -> None:
    adapter = _adapter(tmp_path)
    monkeypatch.setattr(
        "jarvis.benchmarking.espeak_ng.run_bounded",
        lambda args, *, limits: execution,
    )
    with pytest.raises(error):
        adapter.synthesize(_entry(), tmp_path / "output")


def test_espeak_adapter_requires_output(monkeypatch, tmp_path: Path) -> None:
    adapter = _adapter(tmp_path)
    monkeypatch.setattr(
        "jarvis.benchmarking.espeak_ng.run_bounded",
        lambda args, *, limits: _execution(),
    )
    with pytest.raises(RuntimeError, match="did not create"):
        adapter.synthesize(_entry(), tmp_path / "output")
