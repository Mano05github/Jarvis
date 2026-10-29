from __future__ import annotations

import gc
import statistics
import subprocess
import sys
import time
from pathlib import Path

import psutil  # type: ignore[import-untyped]

from jarvis.runtime.broker import WindowsJobObject
from jarvis.runtime.memory import (
    MemoryGovernor,
    SystemMemorySnapshot,
    load_memory_runtime_config,
)
from jarvis.runtime.native_speech import (
    NativeSpeechState,
    NativeSpeechWorkerAdapter,
    NativeSpeechWorkerConfig,
    NativeSpeechWorkerError,
)

MIB = 1024**2
GIB = 1024**3
SOAK_CYCLES = 100
checks = 0


def check(condition: bool, message: str) -> None:
    global checks
    checks += 1
    if not condition:
        raise AssertionError(message)


def governor(project_root: Path) -> MemoryGovernor:
    snapshot = SystemMemorySnapshot(
        available_physical_bytes=8 * GIB,
        total_physical_bytes=16 * GIB,
        commit_used_bytes=8 * GIB,
        commit_limit_bytes=24 * GIB,
        captured_monotonic=time.monotonic(),
    )
    return MemoryGovernor(
        load_memory_runtime_config(project_root / "config/runtime/memory-policy.toml"),
        snapshot_provider=lambda: snapshot,
    )


def config(executable: Path, *, timeout: float = 2.0) -> NativeSpeechWorkerConfig:
    return NativeSpeechWorkerConfig(
        executable=executable,
        startup_timeout_seconds=timeout,
        response_timeout_seconds=timeout,
        shutdown_timeout_seconds=1.0,
    )


def hook_factory(hook: str):
    def factory(command: list[str]) -> subprocess.Popen[bytes]:
        return subprocess.Popen(
            [*command, hook],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            bufsize=0,
        )

    return factory


def process_stopped(process_id: int) -> bool:
    deadline = time.monotonic() + 2.0
    while psutil.pid_exists(process_id) and time.monotonic() < deadline:
        time.sleep(0.01)
    return not psutil.pid_exists(process_id)


def percentile_95(values: list[float]) -> float:
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int(len(ordered) * 0.95) - 1))
    return ordered[index]


def run_soak(project_root: Path, executable: Path) -> dict[str, float | int]:
    memory = governor(project_root)
    parent = psutil.Process()
    handles_before = parent.num_handles()
    startup_ms: list[float] = []
    response_ms: list[float] = []
    private_bytes: list[int] = []
    job_bytes: list[int] = []

    for cycle in range(SOAK_CYCLES):
        adapter = NativeSpeechWorkerAdapter(
            config(executable),
            memory,
            certification_mode=True,
            job_factory=WindowsJobObject,
        )
        startup = adapter.start()
        check(adapter.containment_verified, f"cycle {cycle}: containment unverified")
        adapter.start_session()
        check(adapter.accept_audio(b"\x00\x00" * 8) == "calculator", "bad partial")
        check(adapter.finish() == "calculator open pannu", "bad final")
        adapter.close()
        metrics = adapter.metrics
        check(metrics.exit_reason == "clean_shutdown", "unclean soak shutdown")
        check(metrics.request_count == 3, "unexpected soak request count")
        check(memory.active_lease_count == 0, "soak lease survived")
        check(process_stopped(startup.process_id), "soak PID survived")
        startup_ms.append(metrics.startup_latency_ms)
        response_ms.append(metrics.maximum_response_latency_ms)
        private_bytes.append(metrics.peak_private_bytes)
        job_bytes.append(metrics.peak_job_bytes)

    check(max(private_bytes) <= 64 * MIB, "governed fake worker exceeded 64 MiB private")
    check(max(job_bytes) <= 640 * MIB, "Job Object peak exceeded its hard limit")
    check(
        statistics.median(private_bytes[-10:]) - statistics.median(private_bytes[:10]) <= 16 * MIB,
        "governed worker private memory drifted",
    )
    gc.collect()
    time.sleep(0.05)
    handles_after = parent.num_handles()
    check(
        handles_after <= handles_before + 4,
        f"governed soak leaked handles: before={handles_before}, after={handles_after}",
    )
    return {
        "cycles": SOAK_CYCLES,
        "startup_p95_ms": round(percentile_95(startup_ms), 3),
        "response_max_p95_ms": round(percentile_95(response_ms), 3),
        "peak_private_bytes": max(private_bytes),
        "peak_job_bytes": max(job_bytes),
    }


def run_fault(
    project_root: Path,
    executable: Path,
    hook: str,
    stage: str,
    expected_code: str,
) -> None:
    memory = governor(project_root)
    adapter = NativeSpeechWorkerAdapter(
        config(executable, timeout=0.25),
        memory,
        certification_mode=True,
        job_factory=WindowsJobObject,
        process_factory=hook_factory(hook),
    )
    try:
        adapter.start()
        if stage == "audio":
            adapter.start_session()
            adapter.accept_audio(b"\x00\x00")
        elif stage == "finish":
            adapter.start_session()
            adapter.finish()
        else:
            check(False, f"fault {hook} unexpectedly started")
    except NativeSpeechWorkerError as error:
        check(error.code == expected_code, f"fault {hook}: got {error.code}")
    else:
        check(False, f"fault {hook} did not fail")
    process_id = adapter.process_id
    check(process_id is not None, f"fault {hook} never spawned")
    check(memory.active_lease_count == 0, f"fault {hook} leaked its lease")
    check(process_stopped(process_id), f"fault {hook} left PID {process_id}")
    check(adapter.state is NativeSpeechState.FAILED, f"fault {hook} state was unsafe")


def run_fault_matrix(project_root: Path, executable: Path) -> None:
    cases = (
        ("--test-exit-before-bootstrap", "start", "worker_stream_closed"),
        ("--test-exit-after-bootstrap", "start", "worker_stream_closed"),
        ("--test-fail-load", "start", "worker_rejected_request"),
        ("--test-stall-after-bootstrap", "start", "worker_response_timeout"),
        ("--test-exit-on-audio", "audio", "worker_stream_closed"),
        ("--test-stall-on-audio", "audio", "worker_response_timeout"),
        ("--test-stall-on-finish", "finish", "worker_response_timeout"),
        ("--test-invalid-utf8-partial", "audio", "worker_text_invalid"),
    )
    for hook, stage, code in cases:
        run_fault(project_root, executable, hook, stage, code)

    memory = governor(project_root)
    adapter = NativeSpeechWorkerAdapter(
        config(executable),
        memory,
        certification_mode=True,
        job_factory=WindowsJobObject,
    )
    first = adapter.start()
    adapter.cancel()
    adapter.reset()
    adapter.start_session()
    adapter.cancel()
    adapter.reset()
    adapter.close()
    check(memory.active_lease_count == 0, "cancellation path leaked its lease")
    check(process_stopped(first.process_id), "cancellation path left a PID")


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: test-governed-native-speech.py WORKER_EXE", file=sys.stderr)
        return 2
    executable = Path(sys.argv[1]).resolve()
    project_root = Path(__file__).resolve().parents[1]
    check(executable.is_file(), f"worker executable not found: {executable}")
    run_fault_matrix(project_root, executable)
    summary = run_soak(project_root, executable)
    print(f"Governed speech certification passed: {checks} checks")
    print(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
