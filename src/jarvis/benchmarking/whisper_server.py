"""Resident localhost-only whisper.cpp server benchmark adapter."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

import psutil  # type: ignore[import-untyped]

from jarvis.benchmarking.process import ExecutionResult
from jarvis.benchmarking.whisper_cpp import TranscriptionResult, _extract_text


@dataclass(frozen=True, slots=True)
class WhisperServerConfig:
    executable: Path
    model: Path
    threads: int = 4
    language: str = "auto"
    startup_timeout_seconds: float = 60.0
    request_timeout_seconds: float = 120.0
    response_bytes: int = 2 * 1024 * 1024

    def validate(self) -> None:
        if not self.executable.is_file():
            raise FileNotFoundError(f"whisper server executable not found: {self.executable}")
        if not self.model.is_file():
            raise FileNotFoundError(f"whisper model not found: {self.model}")
        if not 1 <= self.threads <= 8:
            raise ValueError("threads must be between 1 and 8")
        if self.language not in {"auto", "en", "ta"}:
            raise ValueError("language must be auto, en or ta")
        if self.startup_timeout_seconds <= 0 or self.request_timeout_seconds <= 0:
            raise ValueError("server timeouts must be positive")
        if self.response_bytes < 1024:
            raise ValueError("response byte limit is too small")


def _free_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _multipart(audio: Path, language: str) -> tuple[bytes, str]:
    boundary = f"jarvis-{uuid4().hex}"
    body = bytearray()

    def field(name: str, value: str) -> None:
        body.extend(f"--{boundary}\r\n".encode())
        body.extend(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode())
        body.extend(value.encode())
        body.extend(b"\r\n")

    field("response_format", "json")
    field("language", language)
    field("temperature", "0.0")
    body.extend(f"--{boundary}\r\n".encode())
    body.extend(
        (
            f'Content-Disposition: form-data; name="file"; filename="{audio.name}"\r\n'
            "Content-Type: audio/wav\r\n\r\n"
        ).encode()
    )
    body.extend(audio.read_bytes())
    body.extend(f"\r\n--{boundary}--\r\n".encode())
    return bytes(body), f"multipart/form-data; boundary={boundary}"


def _usage(process: psutil.Process) -> tuple[int, float]:
    try:
        memory = process.memory_info().rss
        cpu = process.cpu_times()
        return memory, cpu.user + cpu.system
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return 0, 0.0


class WhisperServerAdapter:
    """Own one loopback-only server process and reuse its loaded model."""

    def __init__(self, config: WhisperServerConfig) -> None:
        config.validate()
        self.config = config
        self._process: subprocess.Popen[bytes] | None = None
        self._tracked: psutil.Process | None = None
        self._port: int | None = None
        self.startup_seconds: float | None = None

    def __enter__(self) -> WhisperServerAdapter:
        self.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    @property
    def endpoint(self) -> str:
        if self._port is None:
            raise RuntimeError("whisper server is not running")
        return f"http://127.0.0.1:{self._port}"

    def start(self) -> None:
        if self._process is not None:
            raise RuntimeError("whisper server is already running")
        port = _free_local_port()
        command = [
            str(self.config.executable),
            "-m",
            str(self.config.model),
            "-t",
            str(self.config.threads),
            "-l",
            self.config.language,
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "-nlp",
        ]
        creation_flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        started = time.perf_counter()
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            shell=False,
            creationflags=creation_flags,
        )
        self._process = process
        self._tracked = psutil.Process(process.pid)
        self._port = port
        deadline = started + self.config.startup_timeout_seconds
        try:
            while time.perf_counter() < deadline:
                if process.poll() is not None:
                    raise RuntimeError(
                        f"whisper server exited during startup with code {process.returncode}"
                    )
                try:
                    with urllib.request.urlopen(f"{self.endpoint}/health", timeout=0.5) as response:
                        if response.status == 200:
                            self.startup_seconds = time.perf_counter() - started
                            return
                except (OSError, TimeoutError, urllib.error.URLError):
                    time.sleep(0.1)
            raise TimeoutError("whisper server did not become healthy before the deadline")
        except Exception:
            self.close()
            raise

    def close(self) -> None:
        process = self._process
        self._process = None
        self._tracked = None
        self._port = None
        if process is None or process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=2.0)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=2.0)

    def transcribe(self, audio: Path, output_directory: Path) -> TranscriptionResult:
        if self._process is None or self._tracked is None:
            raise RuntimeError("whisper server is not running")
        if not audio.is_file():
            raise FileNotFoundError(f"audio file not found: {audio}")
        body, content_type = _multipart(audio, self.config.language)
        request = urllib.request.Request(
            f"{self.endpoint}/inference",
            data=body,
            headers={"Content-Type": content_type},
            method="POST",
        )
        before_rss, before_cpu = _usage(self._tracked)
        peak_rss = [before_rss]
        stop = threading.Event()

        def sample() -> None:
            while not stop.wait(0.05):
                rss, _cpu = _usage(self._tracked)
                peak_rss[0] = max(peak_rss[0], rss)

        sampler = threading.Thread(target=sample, daemon=True)
        started = time.perf_counter()
        sampler.start()
        try:
            with urllib.request.urlopen(
                request, timeout=self.config.request_timeout_seconds
            ) as response:
                payload_bytes = response.read(self.config.response_bytes + 1)
                if len(payload_bytes) > self.config.response_bytes:
                    raise RuntimeError("whisper server response exceeded the byte limit")
        finally:
            stop.set()
            sampler.join(timeout=1.0)
        elapsed = time.perf_counter() - started
        final_rss, final_cpu = _usage(self._tracked)
        peak_rss[0] = max(peak_rss[0], final_rss)
        payload = json.loads(payload_bytes.decode("utf-8"))
        output_directory.mkdir(parents=True, exist_ok=True)
        structured_output = output_directory / f"{audio.stem}.server.json"
        structured_output.write_bytes(payload_bytes)
        execution = ExecutionResult(
            args=("POST", f"{self.endpoint}/inference"),
            exit_code=0,
            timed_out=False,
            elapsed_seconds=elapsed,
            peak_rss_bytes=peak_rss[0],
            cpu_seconds=max(0.0, final_cpu - before_cpu),
            stdout_tail="",
            stderr_tail="",
            output_truncated=False,
        )
        return TranscriptionResult(_extract_text(payload), execution, structured_output)
