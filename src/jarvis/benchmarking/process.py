"""Bounded subprocess execution and resource measurement for local engines."""

from __future__ import annotations

import os
import subprocess
import threading
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

import psutil  # type: ignore[import-untyped]


@dataclass(frozen=True, slots=True)
class ExecutionLimits:
    timeout_seconds: float = 120.0
    output_bytes: int = 256 * 1024
    sample_interval_seconds: float = 0.05

    def __post_init__(self) -> None:
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if self.output_bytes <= 0:
            raise ValueError("output_bytes must be positive")
        if self.sample_interval_seconds <= 0:
            raise ValueError("sample_interval_seconds must be positive")


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    args: tuple[str, ...]
    exit_code: int
    timed_out: bool
    elapsed_seconds: float
    peak_rss_bytes: int
    cpu_seconds: float
    stdout_tail: str
    stderr_tail: str
    output_truncated: bool


class _BoundedCollector:
    def __init__(self, limit: int) -> None:
        self._limit = limit
        self._data = bytearray()
        self.truncated = False
        self._lock = threading.Lock()

    def append(self, value: bytes) -> None:
        with self._lock:
            self._data.extend(value)
            if len(self._data) > self._limit:
                del self._data[: len(self._data) - self._limit]
                self.truncated = True

    def text(self) -> str:
        with self._lock:
            return self._data.decode("utf-8", errors="replace")


def _drain(stream: BinaryIO, collector: _BoundedCollector) -> None:
    try:
        while chunk := stream.read(64 * 1024):
            collector.append(chunk)
    finally:
        stream.close()


def _usage(process: psutil.Process) -> tuple[int, float]:
    rss = 0
    cpu = 0.0
    processes = [process]
    try:
        processes.extend(process.children(recursive=True))
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass
    for item in processes:
        try:
            rss += item.memory_info().rss
            times = item.cpu_times()
            cpu += times.user + times.system
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return rss, cpu


def _terminate_tree(process: psutil.Process) -> None:
    try:
        descendants = process.children(recursive=True)
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        descendants = []
    for item in reversed(descendants):
        try:
            item.terminate()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    try:
        process.terminate()
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass
    _, alive = psutil.wait_procs([*descendants, process], timeout=1.0)
    for item in alive:
        try:
            item.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass


def run_bounded(
    args: Sequence[str],
    *,
    limits: ExecutionLimits | None = None,
    cwd: Path | None = None,
    environment: Mapping[str, str] | None = None,
) -> ExecutionResult:
    """Run an argument-vector command without a shell and supervise its resource use."""

    selected_limits = limits or ExecutionLimits()
    if not args or any(not isinstance(arg, str) or not arg for arg in args):
        raise ValueError("args must contain non-empty strings")

    merged_environment = os.environ.copy()
    if environment:
        merged_environment.update(environment)
    creation_flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    process = subprocess.Popen(
        list(args),
        cwd=cwd,
        env=merged_environment,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        shell=False,
        creationflags=creation_flags,
    )
    if process.stdout is None or process.stderr is None:
        raise RuntimeError("subprocess pipes were not created")

    stdout = _BoundedCollector(selected_limits.output_bytes)
    stderr = _BoundedCollector(selected_limits.output_bytes)
    threads = (
        threading.Thread(target=_drain, args=(process.stdout, stdout), daemon=True),
        threading.Thread(target=_drain, args=(process.stderr, stderr), daemon=True),
    )
    for thread in threads:
        thread.start()

    tracked = psutil.Process(process.pid)
    started = time.perf_counter()
    peak_rss = 0
    cpu_seconds = 0.0
    timed_out = False
    while process.poll() is None:
        rss, cpu = _usage(tracked)
        peak_rss = max(peak_rss, rss)
        cpu_seconds = max(cpu_seconds, cpu)
        if time.perf_counter() - started >= selected_limits.timeout_seconds:
            timed_out = True
            _terminate_tree(tracked)
            break
        time.sleep(selected_limits.sample_interval_seconds)

    exit_code = process.wait()
    for thread in threads:
        thread.join(timeout=2.0)
    elapsed = time.perf_counter() - started
    return ExecutionResult(
        args=tuple(args),
        exit_code=exit_code,
        timed_out=timed_out,
        elapsed_seconds=elapsed,
        peak_rss_bytes=peak_rss,
        cpu_seconds=cpu_seconds,
        stdout_tail=stdout.text(),
        stderr_tail=stderr.text(),
        output_truncated=stdout.truncated or stderr.truncated,
    )
