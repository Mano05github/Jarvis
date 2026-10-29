import json
import subprocess
import wave
from pathlib import Path
from types import SimpleNamespace

import pytest

from jarvis.benchmarking import whisper_server
from jarvis.benchmarking.whisper_server import (
    WhisperServerAdapter,
    WhisperServerConfig,
    _multipart,
)


class FakeProcess:
    def __init__(self) -> None:
        self.pid = 4321
        self.returncode = None
        self.terminated = False
        self.killed = False

    def poll(self):
        return self.returncode

    def terminate(self) -> None:
        self.terminated = True
        self.returncode = 0

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9

    def wait(self, timeout=None):
        return self.returncode or 0


class FakeTrackedProcess:
    def __init__(self) -> None:
        self.samples = 0

    def memory_info(self):
        self.samples += 1
        return SimpleNamespace(rss=400_000_000 + self.samples)

    def cpu_times(self):
        return SimpleNamespace(user=float(self.samples), system=0.5)


class FakeResponse:
    def __init__(self, payload: bytes, status: int = 200) -> None:
        self.payload = payload
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def read(self, limit: int = -1) -> bytes:
        return self.payload if limit < 0 else self.payload[:limit]


def create_config(tmp_path: Path, **changes) -> WhisperServerConfig:
    executable = tmp_path / "whisper-server.exe"
    model = tmp_path / "model.bin"
    executable.touch()
    model.touch()
    values = {"executable": executable, "model": model, **changes}
    return WhisperServerConfig(**values)


def write_wav(path: Path) -> None:
    with wave.open(str(path), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(16_000)
        audio.writeframes(b"\x00\x00" * 1_600)


def test_multipart_contains_local_audio_and_fields(tmp_path: Path) -> None:
    audio = tmp_path / "sample.wav"
    write_wav(audio)
    body, content_type = _multipart(audio, "en")
    assert content_type.startswith("multipart/form-data; boundary=jarvis-")
    assert b'name="language"' in body
    assert b"\r\nen\r\n" in body
    assert b'filename="sample.wav"' in body


@pytest.mark.parametrize(
    ("changes", "error"),
    [
        ({"threads": 0}, "threads"),
        ({"language": "fr"}, "language"),
        ({"request_timeout_seconds": 0}, "timeouts"),
        ({"response_bytes": 100}, "byte limit"),
    ],
)
def test_server_config_rejects_unsafe_values(tmp_path: Path, changes, error: str) -> None:
    with pytest.raises(ValueError, match=error):
        create_config(tmp_path, **changes).validate()


def test_resident_adapter_start_transcribe_and_close(monkeypatch, tmp_path: Path) -> None:
    process = FakeProcess()
    tracked = FakeTrackedProcess()
    calls: list[object] = []

    def fake_urlopen(request, timeout):
        calls.append(request)
        if isinstance(request, str):
            return FakeResponse(b'{"status":"ok"}')
        return FakeResponse(json.dumps({"text": " hello "}).encode())

    monkeypatch.setattr(whisper_server, "_free_local_port", lambda: 19090)
    monkeypatch.setattr(
        whisper_server.subprocess,
        "Popen",
        lambda command, **kwargs: process,
    )
    monkeypatch.setattr(whisper_server.psutil, "Process", lambda _pid: tracked)
    monkeypatch.setattr(whisper_server.urllib.request, "urlopen", fake_urlopen)
    audio = tmp_path / "sample.wav"
    write_wav(audio)

    adapter = WhisperServerAdapter(create_config(tmp_path, language="en"))
    with adapter:
        assert adapter.endpoint == "http://127.0.0.1:19090"
        assert adapter.startup_seconds is not None
        result = adapter.transcribe(audio, tmp_path / "artifacts")
        assert result.hypothesis == "hello"
        assert result.execution.peak_rss_bytes >= 400_000_000
        assert result.execution.cpu_seconds >= 0
        assert result.structured_output.is_file()
        with pytest.raises(RuntimeError, match="already running"):
            adapter.start()

    assert process.terminated is True
    assert len(calls) == 2


def test_adapter_requires_running_server(tmp_path: Path) -> None:
    adapter = WhisperServerAdapter(create_config(tmp_path))
    with pytest.raises(RuntimeError, match="not running"):
        _ = adapter.endpoint
    with pytest.raises(RuntimeError, match="not running"):
        adapter.transcribe(tmp_path / "sample.wav", tmp_path / "output")
    adapter.close()


def test_close_kills_server_that_does_not_terminate(monkeypatch, tmp_path: Path) -> None:
    process = FakeProcess()
    process.poll = lambda: None

    def timeout_wait(timeout=None):
        if not process.killed:
            raise subprocess.TimeoutExpired("server", timeout)
        return -9

    process.wait = timeout_wait
    adapter = WhisperServerAdapter(create_config(tmp_path))
    adapter._process = process
    adapter.close()
    assert process.killed is True
