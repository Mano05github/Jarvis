from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from jarvis.benchmarking.faster_whisper_worker import (
    FasterWhisperWorkerAdapter,
    FasterWhisperWorkerConfig,
    _usage,
)
from jarvis.runtime.memory import (
    MemoryGovernor,
    SystemMemorySnapshot,
    load_memory_runtime_config,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]

FAKE_WORKER = """
import json
import sys
print(json.dumps({"status": "awaiting_start"}), flush=True)
start = json.loads(sys.stdin.readline())
if start.get("command") != "start":
    raise RuntimeError("missing start")
print(json.dumps({"status": "ready", "startup_seconds": 0.01}), flush=True)
for line in sys.stdin:
    request = json.loads(line)
    if request.get("command") == "shutdown":
        print(json.dumps({"status": "stopped"}), flush=True)
        break
    print(json.dumps({
        "status": "completed",
        "request_id": request["request_id"],
        "text": "notepad open pannu",
        "language": "ta",
        "language_probability": 0.9,
        "worker_elapsed_seconds": 0.01,
    }), flush=True)
"""


def memory_governor() -> MemoryGovernor:
    gib = 1024**3
    snapshot = SystemMemorySnapshot(
        available_physical_bytes=8 * gib,
        total_physical_bytes=16 * gib,
        commit_used_bytes=8 * gib,
        commit_limit_bytes=24 * gib,
        captured_monotonic=1,
    )
    config = load_memory_runtime_config(PROJECT_ROOT / "config" / "runtime" / "memory-policy.toml")
    return MemoryGovernor(config, snapshot_provider=lambda: snapshot)


class FakeProcess:
    def __init__(self, rss: int, cpu: float, children: list[FakeProcess] | None = None):
        self.rss = rss
        self.cpu = cpu
        self.descendants = children or []

    def children(self, *, recursive: bool) -> list[FakeProcess]:
        assert recursive
        return self.descendants

    def memory_info(self) -> SimpleNamespace:
        return SimpleNamespace(rss=self.rss)

    def cpu_times(self) -> SimpleNamespace:
        return SimpleNamespace(user=self.cpu, system=0.0)


def test_resident_worker_round_trip(tmp_path: Path) -> None:
    worker = tmp_path / "worker.py"
    worker.write_text(FAKE_WORKER, encoding="utf-8")
    model = tmp_path / "model"
    model.mkdir()
    audio = tmp_path / "sample.wav"
    audio.touch()
    config = FasterWhisperWorkerConfig(
        python=Path(sys.executable),
        worker=worker,
        model=model,
        startup_timeout_seconds=5,
        request_timeout_seconds=5,
    )

    governor = memory_governor()
    with FasterWhisperWorkerAdapter(
        config, memory_governor=governor, certification_mode=True
    ) as adapter:
        assert adapter.startup_seconds == pytest.approx(0.01)
        with pytest.raises(RuntimeError, match="already running"):
            adapter.start()
        with pytest.raises(FileNotFoundError, match="audio file"):
            adapter.transcribe(tmp_path / "missing.wav", tmp_path / "output")
        result = adapter.transcribe(audio, tmp_path / "output")
        evidence = adapter.memory_evidence()

    assert result.hypothesis == "notepad open pannu"
    assert result.execution.exit_code == 0
    assert result.structured_output.is_file()
    assert evidence["certification_mode"] is True
    assert governor.active_lease_count == 0


def test_worker_config_rejects_invalid_compute_type(tmp_path: Path) -> None:
    python = tmp_path / "python.exe"
    worker = tmp_path / "worker.py"
    model = tmp_path / "model"
    python.touch()
    worker.touch()
    model.mkdir()
    config = FasterWhisperWorkerConfig(
        python=python,
        worker=worker,
        model=model,
        compute_type="float16",
    )
    with pytest.raises(ValueError, match="compute type"):
        config.validate()


def test_worker_command_includes_validated_hotwords(tmp_path: Path) -> None:
    python = tmp_path / "python.exe"
    worker = tmp_path / "worker.py"
    model = tmp_path / "model"
    python.touch()
    worker.touch()
    model.mkdir()
    config = FasterWhisperWorkerConfig(
        python=python,
        worker=worker,
        model=model,
        hotwords="Notepad VS Code",
        beam_size=3,
        word_timestamps=True,
    )

    adapter = FasterWhisperWorkerAdapter(
        config, memory_governor=memory_governor(), certification_mode=True
    )

    assert adapter._command()[-6:] == [
        "--beam-size",
        "3",
        "--hotwords",
        "Notepad VS Code",
        "--word-timestamps",
        "--startup-gated",
    ]
    with pytest.raises(ValueError, match="hotwords"):
        replace(config, hotwords="\n").validate()
    with pytest.raises(ValueError, match="beam size"):
        replace(config, beam_size=0).validate()


def test_worker_config_validates_paths_limits_and_language(tmp_path: Path) -> None:
    python = tmp_path / "python.exe"
    worker = tmp_path / "worker.py"
    model = tmp_path / "model"
    python.touch()
    worker.touch()
    model.mkdir()
    valid = FasterWhisperWorkerConfig(python=python, worker=worker, model=model)
    valid.validate()

    checks = (
        (replace(valid, python=tmp_path / "missing-python.exe"), "Python"),
        (replace(valid, worker=tmp_path / "missing-worker.py"), "script"),
        (replace(valid, model=tmp_path / "missing-model"), "model"),
        (replace(valid, threads=0), "threads"),
        (replace(valid, language="fr"), "language"),
        (replace(valid, startup_timeout_seconds=0), "timeouts"),
    )
    for config, message in checks:
        with pytest.raises((ValueError, FileNotFoundError), match=message):
            config.validate()


def test_usage_aggregates_worker_process_tree() -> None:
    child = FakeProcess(200, 2.0)
    parent = FakeProcess(100, 1.0, [child])

    assert _usage(parent) == (300, 3.0)


def test_startup_cancellation_releases_containment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    worker = tmp_path / "worker.py"
    worker.write_text(FAKE_WORKER, encoding="utf-8")
    model = tmp_path / "model"
    model.mkdir()
    memory = memory_governor()
    adapter = FasterWhisperWorkerAdapter(
        FasterWhisperWorkerConfig(python=Path(sys.executable), worker=worker, model=model),
        memory_governor=memory,
        certification_mode=True,
    )

    def cancel(_timeout: float) -> dict[str, object]:
        raise KeyboardInterrupt

    monkeypatch.setattr(adapter, "_receive", cancel)
    with pytest.raises(KeyboardInterrupt):
        adapter.start()
    assert memory.active_lease_count == 0
