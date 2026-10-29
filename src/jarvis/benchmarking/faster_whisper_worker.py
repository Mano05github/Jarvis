"""Supervised resident faster-whisper worker adapter."""

from __future__ import annotations

import json
import os
import queue
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

import psutil  # type: ignore[import-untyped]

from jarvis.benchmarking.process import ExecutionResult
from jarvis.benchmarking.whisper_cpp import TranscriptionResult
from jarvis.runtime.memory import MemoryGovernor
from jarvis.runtime.worker import GovernedWorkerSlot


@dataclass(frozen=True, slots=True)
class FasterWhisperWorkerConfig:
    python: Path
    worker: Path
    model: Path
    threads: int = 4
    language: str = "ta"
    compute_type: str = "int8"
    hotwords: str | None = None
    beam_size: int = 5
    word_timestamps: bool = False
    startup_timeout_seconds: float = 180.0
    request_timeout_seconds: float = 120.0

    def validate(self) -> None:
        if not self.python.is_file():
            raise FileNotFoundError(f"worker Python not found: {self.python}")
        if not self.worker.is_file():
            raise FileNotFoundError(f"worker script not found: {self.worker}")
        if not self.model.is_dir():
            raise FileNotFoundError(f"CTranslate2 model not found: {self.model}")
        if not 1 <= self.threads <= 8:
            raise ValueError("threads must be between 1 and 8")
        if self.language not in {"auto", "en", "ta"}:
            raise ValueError("language must be auto, en or ta")
        if self.compute_type not in {"int8", "int8_float32", "float32"}:
            raise ValueError("unsupported CPU compute type")
        if not 1 <= self.beam_size <= 10:
            raise ValueError("beam size must be between 1 and 10")
        if self.hotwords is not None and (
            not self.hotwords.strip()
            or len(self.hotwords) > 2_048
            or not self.hotwords.isprintable()
        ):
            raise ValueError("hotwords must be printable text of at most 2048 characters")
        if self.startup_timeout_seconds <= 0 or self.request_timeout_seconds <= 0:
            raise ValueError("worker timeouts must be positive")


def _usage(process: psutil.Process) -> tuple[int, float]:
    memory = 0
    cpu_seconds = 0.0
    processes = [process]
    try:
        processes.extend(process.children(recursive=True))
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass
    for item in processes:
        try:
            memory += item.memory_info().rss
            cpu = item.cpu_times()
            cpu_seconds += cpu.user + cpu.system
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return memory, cpu_seconds


def _private_usage(process: psutil.Process) -> int:
    private_bytes = 0
    processes = [process]
    try:
        processes.extend(process.children(recursive=True))
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass
    for item in processes:
        try:
            values = item.memory_info()._asdict()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
        private_bytes += int(values.get("private", values.get("rss", 0)))
    return private_bytes


class FasterWhisperWorkerAdapter:
    """Own one isolated Python worker and reuse its loaded model."""

    def __init__(
        self,
        config: FasterWhisperWorkerConfig,
        *,
        memory_governor: MemoryGovernor,
        certification_mode: bool = False,
        worker_profile_name: str = "faster-whisper",
    ) -> None:
        config.validate()
        self.config = config
        self._process: subprocess.Popen[str] | None = None
        self._tracked: psutil.Process | None = None
        self._responses: queue.Queue[str] = queue.Queue()
        self._stderr: list[str] = []
        self._stdout_thread: threading.Thread | None = None
        self._stderr_thread: threading.Thread | None = None
        self.startup_seconds: float | None = None
        self.peak_private_bytes = 0
        self.peak_rss_bytes = 0
        self._slot = GovernedWorkerSlot(
            memory_governor,
            worker_profile_name,
            certification_mode=certification_mode,
        )
        self._certification_mode = certification_mode

    def __enter__(self) -> FasterWhisperWorkerAdapter:
        self.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def _command(self) -> list[str]:
        command = [
            str(self.config.python),
            str(self.config.worker),
            "--model",
            str(self.config.model),
            "--threads",
            str(self.config.threads),
            "--compute-type",
            self.config.compute_type,
            "--language",
            self.config.language,
            "--beam-size",
            str(self.config.beam_size),
        ]
        if self.config.hotwords is not None:
            command.extend(("--hotwords", self.config.hotwords))
        if self.config.word_timestamps:
            command.append("--word-timestamps")
        command.append("--startup-gated")
        return command

    def start(self) -> None:
        if self._process is not None:
            raise RuntimeError("faster-whisper worker is already running")
        environment = os.environ.copy()
        environment.update(
            {
                "HF_HUB_OFFLINE": "1",
                "TRANSFORMERS_OFFLINE": "1",
                "TOKENIZERS_PARALLELISM": "false",
                "PYTHONUTF8": "1",
            }
        )
        creation_flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        self._slot.start()
        try:
            process = subprocess.Popen(
                self._command(),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                shell=False,
                creationflags=creation_flags,
                env=environment,
            )
        except BaseException:
            self._slot.close()
            raise
        self._process = process
        self._tracked = psutil.Process(process.pid)
        stdout = process.stdout
        stderr = process.stderr
        assert stdout is not None
        assert stderr is not None

        def read_stdout() -> None:
            for line in stdout:
                self._responses.put(line)

        def read_stderr() -> None:
            for line in stderr:
                self._stderr.append(line.rstrip())
                del self._stderr[:-200]

        self._stdout_thread = threading.Thread(target=read_stdout, daemon=True)
        self._stderr_thread = threading.Thread(target=read_stderr, daemon=True)
        self._stdout_thread.start()
        self._stderr_thread.start()
        startup_deadline = time.monotonic() + self.config.startup_timeout_seconds
        try:
            waiting = self._receive(self.config.startup_timeout_seconds)
            if waiting.get("status") != "awaiting_start":
                raise RuntimeError(f"worker did not honor startup gate: {waiting}")
            self._slot.assign_pid(process.pid)
            assert process.stdin is not None
            process.stdin.write('{"command":"start"}\n')
            process.stdin.flush()
            remaining = max(0.001, startup_deadline - time.monotonic())
            ready = self._receive(remaining)
            if ready.get("status") != "ready":
                raise RuntimeError(f"worker did not become ready: {ready}")
            startup_seconds = ready.get("startup_seconds")
            if not isinstance(startup_seconds, int | float):
                raise ValueError("worker ready response lacks startup timing")
            self.startup_seconds = float(startup_seconds)
            assert self._tracked is not None
            rss, _cpu = _usage(self._tracked)
            private = _private_usage(self._tracked)
            self.peak_rss_bytes = max(self.peak_rss_bytes, rss)
            self.peak_private_bytes = max(self.peak_private_bytes, private)
            self._slot.update_observed_private_bytes(private)
        except BaseException:
            self.close()
            raise

    def _receive(self, timeout: float) -> dict[str, object]:
        process = self._process
        if process is None:
            raise RuntimeError("worker is not running")
        try:
            line = self._responses.get(timeout=timeout)
        except queue.Empty as error:
            if process.poll() is not None:
                raise RuntimeError(
                    f"worker exited with code {process.returncode}: {' '.join(self._stderr[-20:])}"
                ) from error
            raise TimeoutError(f"worker response exceeded {timeout:.1f} seconds") from error
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError("worker response must be a JSON object")
        return value

    def close(self) -> None:
        process = self._process
        self._process = None
        self._tracked = None
        try:
            if process is not None and process.poll() is None:
                try:
                    if process.stdin is not None:
                        process.stdin.write('{"command":"shutdown"}\n')
                        process.stdin.flush()
                    process.wait(timeout=5.0)
                except (BrokenPipeError, subprocess.TimeoutExpired):
                    process.kill()
                    process.wait(timeout=5.0)
        finally:
            self._slot.close()

    def transcribe(self, audio: Path, output_directory: Path) -> TranscriptionResult:
        process = self._process
        tracked = self._tracked
        if process is None or tracked is None or process.stdin is None:
            raise RuntimeError("worker is not running")
        if not audio.is_file():
            raise FileNotFoundError(f"audio file not found: {audio}")
        request_id = uuid4().hex
        request = {
            "command": "transcribe",
            "request_id": request_id,
            "audio": str(audio.resolve()),
        }
        before_rss, before_cpu = _usage(tracked)
        before_private = _private_usage(tracked)
        peak_rss = [before_rss]
        peak_private = [before_private]
        stop = threading.Event()

        def sample() -> None:
            while not stop.wait(0.05):
                rss, _cpu = _usage(tracked)
                private = _private_usage(tracked)
                peak_rss[0] = max(peak_rss[0], rss)
                peak_private[0] = max(peak_private[0], private)

        sampler = threading.Thread(target=sample, daemon=True)
        started = time.perf_counter()
        sampler.start()
        try:
            process.stdin.write(json.dumps(request) + "\n")
            process.stdin.flush()
            try:
                response = self._receive(self.config.request_timeout_seconds)
            except BaseException:
                self.close()
                raise
        finally:
            stop.set()
            sampler.join(timeout=1.0)
        elapsed = time.perf_counter() - started
        final_rss, final_cpu = _usage(tracked)
        final_private = _private_usage(tracked)
        peak_rss[0] = max(peak_rss[0], final_rss)
        peak_private[0] = max(peak_private[0], final_private)
        self.peak_rss_bytes = max(self.peak_rss_bytes, peak_rss[0])
        self.peak_private_bytes = max(self.peak_private_bytes, peak_private[0])
        self._slot.update_observed_private_bytes(final_private)
        if response.get("request_id") != request_id:
            raise RuntimeError("worker response ID mismatch")
        if response.get("status") != "completed":
            raise RuntimeError(f"worker transcription failed: {response.get('error')}")
        text = response.get("text")
        if not isinstance(text, str):
            raise ValueError("worker response did not contain transcript text")
        output_directory.mkdir(parents=True, exist_ok=True)
        structured_output = output_directory / f"{audio.stem}.faster-whisper.json"
        structured_output.write_text(
            json.dumps(response, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        execution = ExecutionResult(
            args=("resident-worker", str(self.config.model)),
            exit_code=0,
            timed_out=False,
            elapsed_seconds=elapsed,
            peak_rss_bytes=peak_rss[0],
            cpu_seconds=max(0.0, final_cpu - before_cpu),
            stdout_tail="",
            stderr_tail="\n".join(self._stderr[-20:]),
            output_truncated=False,
        )
        return TranscriptionResult(text.strip(), execution, structured_output)

    def memory_evidence(self) -> dict[str, object]:
        profile = self._slot.governor.config.profiles[self._slot.profile_name]
        return {
            "profile_name": profile.name,
            "certification_mode": self._certification_mode,
            "profile_certified": profile.certified,
            "peak_rss_bytes": self.peak_rss_bytes,
            "peak_private_bytes": self.peak_private_bytes,
            "hard_process_limit_bytes": profile.hard_process_limit_bytes,
            "hard_job_limit_bytes": profile.hard_job_limit_bytes,
            "active_process_limit": profile.active_process_limit,
        }
