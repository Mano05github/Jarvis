from __future__ import annotations

import sys
import time
import wave
from dataclasses import replace
from pathlib import Path

import pytest

from jarvis.benchmarking.mms_vits_worker import MmsVitsWorkerAdapter, MmsVitsWorkerConfig
from jarvis.benchmarking.tts import TTSEntry

FAKE_WORKER = r"""
import json
import sys
import wave
from pathlib import Path

print(json.dumps({"status": "ready", "startup_seconds": 0.02}), flush=True)
for line in sys.stdin:
    request = json.loads(line)
    if request.get("command") == "shutdown":
        print(json.dumps({"status": "stopped"}), flush=True)
        break
    output = Path(request["output"])
    output.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(output), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(16000)
        audio.writeframes(b"\0\0" * 1600)
    print(json.dumps({
        "status": "completed",
        "request_id": request["request_id"],
        "audio_file": str(output.resolve()),
    }), flush=True)
"""


def test_resident_mms_worker_round_trip(tmp_path: Path) -> None:
    worker = tmp_path / "worker.py"
    worker.write_text(FAKE_WORKER, encoding="utf-8")
    model = tmp_path / "model"
    model.mkdir()
    config = MmsVitsWorkerConfig(
        python=Path(sys.executable),
        worker=worker,
        model=model,
        startup_timeout_seconds=30,
        request_timeout_seconds=5,
    )
    entry = TTSEntry(
        utterance_id="ta_sample_001",
        language="ta",
        text="வணக்கம்",
        category="conversation",
        split="held-out",
    )

    with MmsVitsWorkerAdapter(config) as adapter:
        assert adapter.startup_seconds == pytest.approx(0.02)
        with pytest.raises(RuntimeError, match="already running"):
            adapter.start()
        result = adapter.synthesize(entry, tmp_path / "output")

    assert result.audio_file.is_file()
    with wave.open(str(result.audio_file), "rb") as audio:
        assert audio.getframerate() == 16_000
    assert result.execution.exit_code == 0


def test_mms_worker_config_validates_paths_and_limits(tmp_path: Path) -> None:
    python = tmp_path / "python.exe"
    worker = tmp_path / "worker.py"
    model = tmp_path / "model"
    python.touch()
    worker.touch()
    model.mkdir()
    valid = MmsVitsWorkerConfig(python=python, worker=worker, model=model)
    valid.validate()

    checks = (
        (replace(valid, python=tmp_path / "missing-python.exe"), "Python"),
        (replace(valid, worker=tmp_path / "missing-worker.py"), "script"),
        (replace(valid, model=tmp_path / "missing-model"), "model"),
        (replace(valid, threads=0), "threads"),
        (replace(valid, seed=-1), "seed"),
        (replace(valid, speaking_rate=0.1), "speaking rate"),
        (replace(valid, noise_scale=-1), "noise scales"),
        (
            replace(valid, pronunciation_lexicon=tmp_path / "missing-lexicon.toml"),
            "pronunciation lexicon",
        ),
        (replace(valid, request_timeout_seconds=0), "timeouts"),
    )
    for config, message in checks:
        with pytest.raises((ValueError, FileNotFoundError), match=message):
            config.validate()


def test_mms_worker_reports_startup_exit_without_waiting_for_timeout(tmp_path: Path) -> None:
    worker = tmp_path / "broken_worker.py"
    worker.write_text("import sys\nprint('missing runtime', file=sys.stderr)\n", encoding="utf-8")
    model = tmp_path / "model"
    model.mkdir()
    config = MmsVitsWorkerConfig(
        python=Path(sys.executable),
        worker=worker,
        model=model,
        startup_timeout_seconds=5,
    )

    started = time.perf_counter()
    with pytest.raises(RuntimeError, match=r"worker exited.*missing runtime"):
        MmsVitsWorkerAdapter(config).start()

    # Coverage and antivirus instrumentation can make Windows process startup
    # take several seconds. An early worker exit must still be reported well
    # before the configured startup deadline.
    assert time.perf_counter() - started < config.startup_timeout_seconds / 2
