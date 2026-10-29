from __future__ import annotations

import io
import json
import shutil
import struct
import time
from contextlib import AbstractContextManager
from pathlib import Path
from types import TracebackType
from typing import BinaryIO, cast
from uuid import UUID, uuid4

import psutil  # type: ignore[import-untyped]
import pytest

from jarvis.runtime.broker import (
    BrokerClient,
    BrokerError,
    BrokerSupervisor,
    BrokerSupervisorConfig,
    ResourceAdmissionPolicy,
    WindowsJobObject,
    _read_frame,
    _write_frame,
)
from jarvis.runtime.memory import (
    MemoryGovernor,
    SystemMemorySnapshot,
    load_memory_runtime_config,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BROKER_DLL = (
    PROJECT_ROOT
    / "native"
    / "Jarvis.WindowsBroker"
    / "bin"
    / "Release"
    / "net8.0-windows"
    / "Jarvis.WindowsBroker.dll"
)


def memory_governor() -> MemoryGovernor:
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


def test_resource_admission_preserves_reserve_and_margin() -> None:
    gib = 1024**3
    policy = ResourceAdmissionPolicy(
        os_reserve_bytes=4 * gib,
        safety_margin_bytes=gib,
        broker_peak_bytes=gib,
    )

    admitted = policy.evaluate(available_bytes=7 * gib)
    denied = policy.evaluate(available_bytes=6 * gib - 1)

    assert admitted.allowed is True
    assert admitted.remaining_bytes == gib
    assert denied.allowed is False
    assert denied.reason == "insufficient_available_memory"


@pytest.mark.parametrize(
    "values",
    [
        {"os_reserve_bytes": 0},
        {"safety_margin_bytes": 0},
        {"broker_peak_bytes": 0},
    ],
)
def test_resource_admission_rejects_invalid_configuration(
    values: dict[str, int],
) -> None:
    with pytest.raises(ValueError, match="positive"):
        ResourceAdmissionPolicy(**values)


def test_resource_admission_rejects_invalid_observations() -> None:
    policy = ResourceAdmissionPolicy(1, 1, 1)
    with pytest.raises(ValueError, match="worker peak"):
        policy.evaluate(available_bytes=10, existing_worker_peak_bytes=-1)
    with pytest.raises(ValueError, match="available memory"):
        policy.evaluate(available_bytes=-1)


@pytest.mark.parametrize(
    "values",
    [
        {"process_memory_limit_bytes": 0},
        {"job_memory_limit_bytes": -1},
        {"active_process_limit": 0},
        {"process_memory_limit_bytes": 2, "job_memory_limit_bytes": 1},
    ],
)
def test_job_object_rejects_unsafe_limits(values: dict[str, int]) -> None:
    with pytest.raises(ValueError, match="limit"):
        WindowsJobObject(**values)


def test_broker_frame_round_trip_and_bounds() -> None:
    stream = io.BytesIO()
    payload = {"schema_version": "1.0", "status": "ok"}
    _write_frame(stream, payload)
    stream.seek(0)
    assert _read_frame(stream) == payload

    with pytest.raises(BrokerError, match="message_truncated"):
        _read_frame(io.BytesIO(b"\x01"))
    with pytest.raises(BrokerError, match="message_length_invalid"):
        _read_frame(io.BytesIO(struct.pack("<I", 65_537)))
    encoded = json.dumps([1, 2]).encode()
    with pytest.raises(BrokerError, match="not_object"):
        _read_frame(io.BytesIO(struct.pack("<I", len(encoded)) + encoded))


class _Duplex:
    def __init__(self, *, mismatched: bool = False, missing_sid: bool = False) -> None:
        self.writes = io.BytesIO()
        self.reads: io.BytesIO | None = None
        self.mismatched = mismatched
        self.missing_sid = missing_sid

    def write(self, data: bytes) -> int:
        return self.writes.write(data)

    def flush(self) -> None:
        return None

    def read(self, length: int = -1) -> bytes:
        if self.reads is None:
            self.writes.seek(0)
            request = _read_frame(self.writes)
            request_id = uuid4() if self.mismatched else UUID(str(request["request_id"]))
            response = io.BytesIO()
            _write_frame(
                response,
                {
                    "schema_version": "1.0",
                    "request_id": str(request_id),
                    "status": "ok",
                    "code": "broker_ready_execution_disabled",
                    "broker_version": "0.1.0",
                    "caller_sid": None if self.missing_sid else "S-1-5-21-test",
                },
            )
            response.seek(0)
            self.reads = response
        return self.reads.read(length)


class _Connection(AbstractContextManager[BinaryIO]):
    def __init__(self, duplex: _Duplex) -> None:
        self.duplex = duplex

    def __enter__(self) -> BinaryIO:
        return cast(BinaryIO, self.duplex)

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        return None


def test_broker_client_binds_health_response() -> None:
    client = BrokerClient(
        "fixture",
        connection_factory=lambda _name, _timeout: _Connection(_Duplex()),
    )
    response = client.health()
    assert response.code == "broker_ready_execution_disabled"
    assert response.caller_sid == "S-1-5-21-test"


@pytest.mark.parametrize(
    ("duplex", "code"),
    [
        (_Duplex(mismatched=True), "broker_response_id_mismatch"),
        (_Duplex(missing_sid=True), "broker_caller_identity_missing"),
    ],
)
def test_broker_client_rejects_unbound_health(duplex: _Duplex, code: str) -> None:
    client = BrokerClient(
        "fixture",
        connection_factory=lambda _name, _timeout: _Connection(duplex),
    )
    with pytest.raises(BrokerError, match=code):
        client.health()


@pytest.mark.skipif(
    not BROKER_DLL.is_file() or shutil.which("dotnet") is None,
    reason="release broker build and .NET SDK are required",
)
def test_supervisor_health_and_job_close_leave_no_orphan(tmp_path: Path) -> None:
    governor = memory_governor()
    supervisor = BrokerSupervisor(
        BrokerSupervisorConfig(
            broker_dll=BROKER_DLL,
            key_path=tmp_path / "capability-key.dpapi",
            startup_timeout_seconds=10,
        ),
        admission=ResourceAdmissionPolicy(1, 1, 1),
        memory_governor=governor,
    )

    health = supervisor.start()
    process_id = supervisor.process_id
    assert health.status == "ok"
    assert process_id is not None
    assert psutil.pid_exists(process_id)
    assert governor.active_lease_count == 1

    supervisor.close()
    deadline = time.monotonic() + 5
    while psutil.pid_exists(process_id) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert not psutil.pid_exists(process_id)
    assert governor.active_lease_count == 0


def test_supervisor_releases_memory_lease_when_validation_fails(tmp_path: Path) -> None:
    governor = memory_governor()
    supervisor = BrokerSupervisor(
        BrokerSupervisorConfig(broker_dll=tmp_path / "missing.dll"),
        memory_governor=governor,
    )

    with pytest.raises(FileNotFoundError):
        supervisor.start()
    assert governor.active_lease_count == 0
