"""Supervised resident worker adapter for an offline MMS VITS model."""

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
from jarvis.benchmarking.tts import Synthesis, TTSEntry
from jarvis.benchmarking.tts_text import PronunciationLexicon


@dataclass(frozen=True, slots=True)
class MmsVitsWorkerConfig:
    python: Path
    worker: Path
    model: Path
    threads: int = 4
    seed: int = 7
    speaking_rate: float = 1.0
    noise_scale: float = 0.667
    noise_scale_duration: float = 0.8
    pronunciation_lexicon: Path | None = None
    startup_timeout_seconds: float = 180.0
    request_timeout_seconds: float = 120.0

    def validate(self) -> None:
        if not self.python.is_file():
            raise FileNotFoundError(f"worker Python not found: {self.python}")
        if not self.worker.is_file():
            raise FileNotFoundError(f"worker script not found: {self.worker}")
        if not self.model.is_dir():
            raise FileNotFoundError(f"MMS VITS model not found: {self.model}")
        if not 1 <= self.threads <= 8:
            raise ValueError("threads must be between 1 and 8")
        if not 0 <= self.seed <= 2_147_483_647:
            raise ValueError("seed must be between 0 and 2147483647")
        if not 0.5 <= self.speaking_rate <= 2.0:
            raise ValueError("speaking rate must be between 0.5 and 2.0")
        if not 0 <= self.noise_scale <= 2.0 or not 0 <= self.noise_scale_duration <= 2.0:
            raise ValueError("noise scales must be between 0 and 2")
        if self.pronunciation_lexicon is not None and not self.pronunciation_lexicon.is_file():
            raise FileNotFoundError(
                f"pronunciation lexicon not found: {self.pronunciation_lexicon}"
            )
        if self.startup_timeout_seconds <= 0 or self.request_timeout_seconds <= 0:
            raise ValueError("worker timeouts must be positive")


@dataclass(frozen=True, slots=True)
class MmsVitsSynthesis:
    audio_file: Path
    execution: ExecutionResult


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


class MmsVitsWorkerAdapter:
    """Own one isolated Python worker and reuse its loaded VITS model."""

    def __init__(self, config: MmsVitsWorkerConfig) -> None:
        config.validate()
        self.config = config
        self._process: subprocess.Popen[str] | None = None
        self._tracked: psutil.Process | None = None
        self._responses: queue.Queue[str] = queue.Queue()
        self._stderr: list[str] = []
        self.startup_seconds: float | None = None
        self._lexicon = (
            PronunciationLexicon.load(config.pronunciation_lexicon)
            if config.pronunciation_lexicon is not None
            else None
        )

    def __enter__(self) -> MmsVitsWorkerAdapter:
        self.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def _command(self) -> list[str]:
        return [
            str(self.config.python),
            str(self.config.worker),
            "--model",
            str(self.config.model),
            "--threads",
            str(self.config.threads),
            "--seed",
            str(self.config.seed),
            "--speaking-rate",
            str(self.config.speaking_rate),
            "--noise-scale",
            str(self.config.noise_scale),
            "--noise-scale-duration",
            str(self.config.noise_scale_duration),
        ]

    def start(self) -> None:
        if self._process is not None:
            raise RuntimeError("MMS VITS worker is already running")
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
        self._process = process
        self._tracked = psutil.Process(process.pid)
        assert process.stdout is not None
        assert process.stderr is not None

        def read_stdout() -> None:
            assert process.stdout is not None
            for line in process.stdout:
                self._responses.put(line)

        def read_stderr() -> None:
            assert process.stderr is not None
            for line in process.stderr:
                self._stderr.append(line.rstrip())
                del self._stderr[:-200]

        threading.Thread(target=read_stdout, daemon=True).start()
        threading.Thread(target=read_stderr, daemon=True).start()
        try:
            ready = self._receive(self.config.startup_timeout_seconds)
            if ready.get("status") != "ready":
                raise RuntimeError(f"worker did not become ready: {ready}")
            startup_seconds = ready.get("startup_seconds")
            if not isinstance(startup_seconds, int | float):
                raise ValueError("worker ready response lacks startup timing")
            self.startup_seconds = float(startup_seconds)
        except Exception:
            self.close()
            raise

    def _receive(self, timeout: float) -> dict[str, object]:
        process = self._process
        if process is None:
            raise RuntimeError("worker is not running")
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                details = " ".join(self._stderr[-20:])
                suffix = f": {details}" if details else ""
                raise TimeoutError(f"worker response exceeded {timeout:.1f} seconds{suffix}")
            try:
                line = self._responses.get(timeout=min(0.1, remaining))
                break
            except queue.Empty as error:
                if process.poll() is None:
                    continue
                details = " ".join(self._stderr[-20:])
                suffix = f": {details}" if details else ""
                raise RuntimeError(
                    f"worker exited with code {process.returncode}{suffix}"
                ) from error
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError("worker response must be a JSON object")
        return value

    def close(self) -> None:
        process = self._process
        self._process = None
        self._tracked = None
        if process is None or process.poll() is not None:
            return
        try:
            if process.stdin is not None:
                process.stdin.write('{"command":"shutdown"}\n')
                process.stdin.flush()
            process.wait(timeout=5.0)
        except (BrokenPipeError, subprocess.TimeoutExpired):
            process.kill()
            process.wait(timeout=5.0)

    def synthesize(self, entry: TTSEntry, output_directory: Path) -> Synthesis:
        process = self._process
        tracked = self._tracked
        if process is None or tracked is None or process.stdin is None:
            raise RuntimeError("worker is not running")
        output_directory.mkdir(parents=True, exist_ok=True)
        output = (output_directory / f"{entry.utterance_id}.wav").resolve()
        request_id = uuid4().hex
        spoken_text = self._lexicon.normalize(entry.text) if self._lexicon else entry.text
        request = {
            "command": "synthesize",
            "request_id": request_id,
            "text": spoken_text,
            "output": str(output),
        }
        before_rss, before_cpu = _usage(tracked)
        peak_rss = [before_rss]
        stop = threading.Event()

        def sample() -> None:
            while not stop.wait(0.05):
                rss, _cpu = _usage(tracked)
                peak_rss[0] = max(peak_rss[0], rss)

        sampler = threading.Thread(target=sample, daemon=True)
        started = time.perf_counter()
        sampler.start()
        try:
            process.stdin.write(json.dumps(request, ensure_ascii=False) + "\n")
            process.stdin.flush()
            try:
                response = self._receive(self.config.request_timeout_seconds)
            except Exception:
                self.close()
                raise
        finally:
            stop.set()
            sampler.join(timeout=1.0)
        elapsed = time.perf_counter() - started
        final_rss, final_cpu = _usage(tracked)
        peak_rss[0] = max(peak_rss[0], final_rss)
        if response.get("request_id") != request_id:
            raise RuntimeError("worker response ID mismatch")
        if response.get("status") != "completed":
            raise RuntimeError(f"worker synthesis failed: {response.get('error')}")
        response_output = response.get("audio_file")
        if not isinstance(response_output, str) or Path(response_output).resolve() != output:
            raise RuntimeError("worker returned an unexpected audio path")
        if not output.is_file():
            raise RuntimeError("worker did not create the requested WAV file")
        execution = ExecutionResult(
            args=("resident-mms-vits-worker", str(self.config.model)),
            exit_code=0,
            timed_out=False,
            elapsed_seconds=elapsed,
            peak_rss_bytes=peak_rss[0],
            cpu_seconds=max(0.0, final_cpu - before_cpu),
            stdout_tail="",
            stderr_tail="\n".join(self._stderr[-20:]),
            output_truncated=False,
        )
        return MmsVitsSynthesis(output, execution)
