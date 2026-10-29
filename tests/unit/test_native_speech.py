from __future__ import annotations

import os
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

import psutil  # type: ignore[import-untyped]
import pytest

from jarvis.runtime.broker import WindowsJobObject
from jarvis.runtime.memory import (
    MemoryAdmissionError,
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

PROJECT_ROOT = Path(__file__).resolve().parents[2]
WORKER = (
    PROJECT_ROOT
    / "storage"
    / "build"
    / "native"
    / "Jarvis.SpeechRuntime"
    / "Release"
    / "jarvis_speech_fake_worker.exe"
)


def governor() -> MemoryGovernor:
    gib = 1024**3
    snapshot = SystemMemorySnapshot(
        available_physical_bytes=8 * gib,
        total_physical_bytes=16 * gib,
        commit_used_bytes=8 * gib,
        commit_limit_bytes=24 * gib,
        captured_monotonic=1,
    )
    return MemoryGovernor(
        load_memory_runtime_config(PROJECT_ROOT / "config" / "runtime" / "memory-policy.toml"),
        snapshot_provider=lambda: snapshot,
    )


@dataclass
class FakeJob:
    contained: bool = True
    assigned_pid: int | None = None
    closed: bool = False
    events: list[str] = field(default_factory=list)

    def assign_pid(self, process_id: int) -> None:
        self.assigned_pid = process_id
        self.events.append("assigned")

    def contains_pid(self, process_id: int) -> bool:
        self.events.append("verified")
        return self.contained and process_id == self.assigned_pid

    def memory_peaks(self) -> tuple[int, int]:
        return (1024, 2048)

    def close(self) -> None:
        self.closed = True
        self.events.append("closed")


def fake_job_factory(job: FakeJob):
    def factory(**_kwargs: object) -> FakeJob:
        return job

    return factory


def hook_process_factory(hook: str):
    def factory(command: list[str]) -> subprocess.Popen[bytes]:
        return subprocess.Popen(
            [*command, hook],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            bufsize=0,
        )

    return factory


def config(*, response_timeout: float = 2.0) -> NativeSpeechWorkerConfig:
    return NativeSpeechWorkerConfig(
        executable=WORKER,
        startup_timeout_seconds=2,
        response_timeout_seconds=response_timeout,
        shutdown_timeout_seconds=1,
    )


def assert_process_stopped(process_id: int) -> None:
    deadline = time.monotonic() + 2
    while psutil.pid_exists(process_id) and time.monotonic() < deadline:
        time.sleep(0.01)
    assert not psutil.pid_exists(process_id)


@pytest.mark.skipif(not WORKER.is_file(), reason="native fake worker must be built")
def test_adapter_full_lifecycle_and_fake_containment() -> None:
    memory = governor()
    job = FakeJob()
    adapter = NativeSpeechWorkerAdapter(
        config(),
        memory,
        certification_mode=True,
        job_factory=fake_job_factory(job),
    )

    startup = adapter.start()
    assert startup.process_id == adapter.process_id
    assert adapter.containment_verified is True
    assert job.events[:2] == ["assigned", "verified"]
    assert adapter.state is NativeSpeechState.READY
    assert memory.active_lease_count == 1

    adapter.start_session()
    assert adapter.accept_audio(b"\x00\x00" * 8) == "calculator"
    assert adapter.finish() == "calculator open pannu"
    adapter.reset()
    adapter.start_session()
    adapter.cancel()
    adapter.reset()
    process_id = startup.process_id
    adapter.close()

    assert adapter.state is NativeSpeechState.CLOSED
    assert job.closed is True
    assert memory.active_lease_count == 0
    assert_process_stopped(process_id)


@pytest.mark.skipif(not WORKER.is_file(), reason="native fake worker must be built")
def test_uncertified_profile_cannot_start_in_normal_mode() -> None:
    memory = governor()
    adapter = NativeSpeechWorkerAdapter(
        config(),
        memory,
        job_factory=fake_job_factory(FakeJob()),
    )

    with pytest.raises(MemoryAdmissionError, match="worker_profile_uncertified"):
        adapter.start()
    assert memory.active_lease_count == 0


@pytest.mark.skipif(not WORKER.is_file(), reason="native fake worker must be built")
def test_failed_containment_prevents_authorization_and_cleans_up() -> None:
    memory = governor()
    job = FakeJob(contained=False)
    adapter = NativeSpeechWorkerAdapter(
        config(),
        memory,
        certification_mode=True,
        job_factory=fake_job_factory(job),
    )

    with pytest.raises(NativeSpeechWorkerError) as caught:
        adapter.start()
    assert caught.value.code == "worker_containment_unverified"
    process_id = job.assigned_pid
    assert process_id is not None
    assert adapter.containment_verified is False
    assert memory.active_lease_count == 0
    assert_process_stopped(process_id)


@pytest.mark.skipif(not WORKER.is_file(), reason="native fake worker must be built")
@pytest.mark.parametrize(
    ("hook", "operation", "code"),
    [
        ("--test-exit-after-bootstrap", "start", "worker_stream_closed"),
        ("--test-invalid-utf8-partial", "audio", "worker_text_invalid"),
        ("--test-stall-on-audio", "audio", "worker_response_timeout"),
    ],
)
def test_adapter_faults_release_process_and_lease(hook: str, operation: str, code: str) -> None:
    memory = governor()
    job = FakeJob()
    adapter = NativeSpeechWorkerAdapter(
        config(response_timeout=0.2),
        memory,
        certification_mode=True,
        job_factory=fake_job_factory(job),
        process_factory=hook_process_factory(hook),
    )

    if operation == "start":
        with pytest.raises(NativeSpeechWorkerError) as caught:
            adapter.start()
    else:
        adapter.start()
        adapter.start_session()
        with pytest.raises(NativeSpeechWorkerError) as caught:
            adapter.accept_audio(b"\x00\x00")
    assert caught.value.code == code
    process_id = job.assigned_pid
    assert process_id is not None
    assert memory.active_lease_count == 0
    assert_process_stopped(process_id)


@pytest.mark.skipif(
    os.name != "nt" or not WORKER.is_file(),
    reason="Windows and a built native fake worker are required",
)
def test_real_job_object_is_verified_before_worker_authorization() -> None:
    memory = governor()
    adapter = NativeSpeechWorkerAdapter(
        config(),
        memory,
        certification_mode=True,
        job_factory=WindowsJobObject,
    )

    startup = adapter.start()
    assert adapter.containment_verified is True
    assert adapter.state is NativeSpeechState.READY
    adapter.close()
    assert_process_stopped(startup.process_id)
    assert memory.active_lease_count == 0
