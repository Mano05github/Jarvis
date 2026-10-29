"""Resource-gated supervision and strict named-pipe client for the Windows broker."""

from __future__ import annotations

import ctypes
import json
import msvcrt
import os
import shutil
import struct
import subprocess
import time
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from typing import Any, BinaryIO, Literal
from uuid import UUID, uuid4

import psutil  # type: ignore[import-untyped]
from pydantic import BaseModel, ConfigDict, Field

from jarvis.runtime.memory import MemoryGovernor, MemoryLease

_GIB = 1024**3
_MIB = 1024**2
_MAXIMUM_MESSAGE_BYTES = 64 * 1024


class BrokerError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class ResourceAdmissionDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    allowed: bool
    available_bytes: int = Field(ge=0)
    required_bytes: int = Field(gt=0)
    remaining_bytes: int
    reason: str


@dataclass(frozen=True, slots=True)
class ResourceAdmissionPolicy:
    os_reserve_bytes: int = 4 * _GIB
    safety_margin_bytes: int = 512 * _MIB
    broker_peak_bytes: int = 256 * _MIB

    def __post_init__(self) -> None:
        values = (
            self.os_reserve_bytes,
            self.safety_margin_bytes,
            self.broker_peak_bytes,
        )
        if any(value <= 0 for value in values):
            raise ValueError("resource admission values must be positive")

    def evaluate(
        self,
        *,
        available_bytes: int | None = None,
        existing_worker_peak_bytes: int = 0,
    ) -> ResourceAdmissionDecision:
        if existing_worker_peak_bytes < 0:
            raise ValueError("existing worker peak cannot be negative")
        available = (
            int(psutil.virtual_memory().available) if available_bytes is None else available_bytes
        )
        if available < 0:
            raise ValueError("available memory cannot be negative")
        required = (
            self.os_reserve_bytes
            + self.safety_margin_bytes
            + self.broker_peak_bytes
            + existing_worker_peak_bytes
        )
        remaining = available - required
        allowed = remaining >= 0
        return ResourceAdmissionDecision(
            allowed=allowed,
            available_bytes=available,
            required_bytes=required,
            remaining_bytes=remaining,
            reason="admitted" if allowed else "insufficient_available_memory",
        )


class BrokerResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"]
    request_id: UUID
    status: Literal["ok", "denied", "error"]
    code: str = Field(min_length=1, max_length=128)
    broker_version: str = Field(min_length=1, max_length=32)
    caller_sid: str | None = Field(default=None, max_length=184)


def _write_frame(stream: BinaryIO, payload: dict[str, object]) -> None:
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    if not 0 < len(encoded) <= _MAXIMUM_MESSAGE_BYTES:
        raise BrokerError("message_length_invalid")
    stream.write(struct.pack("<I", len(encoded)))
    stream.write(encoded)
    stream.flush()


def _read_exact(stream: BinaryIO, length: int) -> bytes:
    chunks = bytearray()
    while len(chunks) < length:
        chunk = stream.read(length - len(chunks))
        if not chunk:
            raise BrokerError("message_truncated")
        chunks.extend(chunk)
    return bytes(chunks)


def _read_frame(stream: BinaryIO) -> dict[str, Any]:
    (length,) = struct.unpack("<I", _read_exact(stream, 4))
    if not 0 < length <= _MAXIMUM_MESSAGE_BYTES:
        raise BrokerError("message_length_invalid")
    try:
        payload = json.loads(_read_exact(stream, length).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise BrokerError("message_json_invalid") from error
    if not isinstance(payload, dict):
        raise BrokerError("message_json_not_object")
    return payload


class _NamedPipeConnection(AbstractContextManager[BinaryIO]):
    _GENERIC_READ = 0x80000000
    _GENERIC_WRITE = 0x40000000
    _OPEN_EXISTING = 3
    _FILE_FLAG_WRITE_THROUGH = 0x80000000
    _SECURITY_SQOS_PRESENT = 0x00100000
    _SECURITY_IDENTIFICATION = 0x00010000
    _ERROR_SEM_TIMEOUT = 121
    _INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

    def __init__(self, pipe_name: str, timeout_ms: int) -> None:
        if os.name != "nt":
            raise BrokerError("windows_required")
        if not pipe_name or len(pipe_name) > 200 or any(c in pipe_name for c in "/\\"):
            raise ValueError("invalid pipe name")
        if not 1 <= timeout_ms <= 300_000:
            raise ValueError("pipe timeout must be between 1 and 300000 ms")
        path = rf"\\.\pipe\{pipe_name}"
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        wait_named_pipe = kernel32.WaitNamedPipeW
        wait_named_pipe.argtypes = (ctypes.c_wchar_p, ctypes.c_uint32)
        wait_named_pipe.restype = ctypes.c_int
        if not wait_named_pipe(path, timeout_ms):
            error = ctypes.get_last_error()
            code = (
                "broker_connect_timeout"
                if error == self._ERROR_SEM_TIMEOUT
                else "broker_unavailable"
            )
            raise BrokerError(code)
        create_file = kernel32.CreateFileW
        create_file.argtypes = (
            ctypes.c_wchar_p,
            ctypes.c_uint32,
            ctypes.c_uint32,
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.c_uint32,
            ctypes.c_void_p,
        )
        create_file.restype = ctypes.c_void_p
        flags = (
            self._FILE_FLAG_WRITE_THROUGH
            | self._SECURITY_SQOS_PRESENT
            | self._SECURITY_IDENTIFICATION
        )
        handle = create_file(
            path,
            self._GENERIC_READ | self._GENERIC_WRITE,
            0,
            None,
            self._OPEN_EXISTING,
            flags,
            None,
        )
        if handle == self._INVALID_HANDLE_VALUE:
            raise BrokerError("broker_connect_failed")
        try:
            descriptor = msvcrt.open_osfhandle(int(handle), os.O_BINARY)
            self._stream: BinaryIO = os.fdopen(descriptor, "r+b", buffering=0)
        except Exception:
            kernel32.CloseHandle(handle)
            raise

    def __enter__(self) -> BinaryIO:
        return self._stream

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self._stream.close()


class BrokerClient:
    def __init__(
        self,
        pipe_name: str,
        *,
        timeout_seconds: float = 5.0,
        connection_factory: Callable[[str, int], AbstractContextManager[BinaryIO]] | None = None,
    ) -> None:
        if not 0 < timeout_seconds <= 300:
            raise ValueError("broker timeout must be between 0 and 300 seconds")
        self.pipe_name = pipe_name
        self.timeout_ms = max(1, int(timeout_seconds * 1000))
        self._connection_factory = connection_factory or _NamedPipeConnection

    def health(self) -> BrokerResponse:
        request_id = uuid4()
        with self._connection_factory(self.pipe_name, self.timeout_ms) as stream:
            _write_frame(
                stream,
                {
                    "schema_version": "1.0",
                    "request_id": str(request_id),
                    "operation": "broker.health",
                },
            )
            response = BrokerResponse.model_validate(_read_frame(stream))
        if response.request_id != request_id:
            raise BrokerError("broker_response_id_mismatch")
        if response.status != "ok" or response.code != "broker_ready_execution_disabled":
            raise BrokerError("broker_not_ready")
        if response.caller_sid is None:
            raise BrokerError("broker_caller_identity_missing")
        return response


class _IoCounters(ctypes.Structure):
    _fields_ = [
        ("read_operation_count", ctypes.c_uint64),
        ("write_operation_count", ctypes.c_uint64),
        ("other_operation_count", ctypes.c_uint64),
        ("read_transfer_count", ctypes.c_uint64),
        ("write_transfer_count", ctypes.c_uint64),
        ("other_transfer_count", ctypes.c_uint64),
    ]


class _BasicLimitInformation(ctypes.Structure):
    _fields_ = [
        ("per_process_user_time_limit", ctypes.c_int64),
        ("per_job_user_time_limit", ctypes.c_int64),
        ("limit_flags", ctypes.c_uint32),
        ("minimum_working_set_size", ctypes.c_size_t),
        ("maximum_working_set_size", ctypes.c_size_t),
        ("active_process_limit", ctypes.c_uint32),
        ("affinity", ctypes.c_size_t),
        ("priority_class", ctypes.c_uint32),
        ("scheduling_class", ctypes.c_uint32),
    ]


class _ExtendedLimitInformation(ctypes.Structure):
    _fields_ = [
        ("basic_limit_information", _BasicLimitInformation),
        ("io_info", _IoCounters),
        ("process_memory_limit", ctypes.c_size_t),
        ("job_memory_limit", ctypes.c_size_t),
        ("peak_process_memory_used", ctypes.c_size_t),
        ("peak_job_memory_used", ctypes.c_size_t),
    ]


class WindowsJobObject(AbstractContextManager["WindowsJobObject"]):
    _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
    _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
    _JOB_OBJECT_LIMIT_BREAKAWAY_OK = 0x00000800
    _JOB_OBJECT_LIMIT_ACTIVE_PROCESS = 0x00000008
    _JOB_OBJECT_LIMIT_PROCESS_MEMORY = 0x00000100
    _JOB_OBJECT_LIMIT_JOB_MEMORY = 0x00000200
    _PROCESS_TERMINATE = 0x0001
    _PROCESS_SET_QUOTA = 0x0100
    _PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

    def __init__(
        self,
        *,
        process_memory_limit_bytes: int | None = None,
        job_memory_limit_bytes: int | None = None,
        active_process_limit: int | None = None,
        allow_breakaway: bool = False,
    ) -> None:
        optional_limits = (
            process_memory_limit_bytes,
            job_memory_limit_bytes,
            active_process_limit,
        )
        if any(value is not None and value <= 0 for value in optional_limits):
            raise ValueError("job limits must be positive when specified")
        if (
            process_memory_limit_bytes is not None
            and job_memory_limit_bytes is not None
            and process_memory_limit_bytes > job_memory_limit_bytes
        ):
            raise ValueError("process memory limit cannot exceed job memory limit")
        if os.name != "nt":
            raise BrokerError("windows_required")
        self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        create_job = self._kernel32.CreateJobObjectW
        create_job.argtypes = (ctypes.c_void_p, ctypes.c_wchar_p)
        create_job.restype = ctypes.c_void_p
        handle = create_job(None, None)
        if not handle:
            raise BrokerError("job_create_failed")
        self._handle: int | None = int(handle)
        information = _ExtendedLimitInformation()
        flags = self._JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if allow_breakaway:
            flags |= self._JOB_OBJECT_LIMIT_BREAKAWAY_OK
        if active_process_limit is not None:
            flags |= self._JOB_OBJECT_LIMIT_ACTIVE_PROCESS
            information.basic_limit_information.active_process_limit = active_process_limit
        if process_memory_limit_bytes is not None:
            flags |= self._JOB_OBJECT_LIMIT_PROCESS_MEMORY
            information.process_memory_limit = process_memory_limit_bytes
        if job_memory_limit_bytes is not None:
            flags |= self._JOB_OBJECT_LIMIT_JOB_MEMORY
            information.job_memory_limit = job_memory_limit_bytes
        information.basic_limit_information.limit_flags = flags
        set_information = self._kernel32.SetInformationJobObject
        set_information.argtypes = (
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_void_p,
            ctypes.c_uint32,
        )
        set_information.restype = ctypes.c_int
        if not set_information(
            self._handle,
            self._JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
            ctypes.byref(information),
            ctypes.sizeof(information),
        ):
            self.close()
            raise BrokerError("job_limits_failed")

    def assign_pid(self, process_id: int) -> None:
        if self._handle is None:
            raise BrokerError("job_closed")
        if process_id <= 0:
            raise ValueError("process ID must be positive")
        open_process = self._kernel32.OpenProcess
        open_process.argtypes = (ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32)
        open_process.restype = ctypes.c_void_p
        process_handle = open_process(
            self._PROCESS_TERMINATE | self._PROCESS_SET_QUOTA,
            False,
            process_id,
        )
        if not process_handle:
            raise BrokerError("job_process_open_failed")
        try:
            assign = self._kernel32.AssignProcessToJobObject
            assign.argtypes = (ctypes.c_void_p, ctypes.c_void_p)
            assign.restype = ctypes.c_int
            if not assign(self._handle, process_handle):
                raise BrokerError("job_assign_failed")
        finally:
            self._kernel32.CloseHandle(process_handle)

    def contains_pid(self, process_id: int) -> bool:
        if self._handle is None:
            raise BrokerError("job_closed")
        if process_id <= 0:
            raise ValueError("process ID must be positive")
        open_process = self._kernel32.OpenProcess
        open_process.argtypes = (ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32)
        open_process.restype = ctypes.c_void_p
        process_handle = open_process(
            self._PROCESS_QUERY_LIMITED_INFORMATION,
            False,
            process_id,
        )
        if not process_handle:
            raise BrokerError("job_process_open_failed")
        try:
            is_process_in_job = self._kernel32.IsProcessInJob
            is_process_in_job.argtypes = (
                ctypes.c_void_p,
                ctypes.c_void_p,
                ctypes.POINTER(ctypes.c_int),
            )
            is_process_in_job.restype = ctypes.c_int
            result = ctypes.c_int(0)
            if not is_process_in_job(
                process_handle,
                self._handle,
                ctypes.byref(result),
            ):
                raise BrokerError("job_membership_query_failed")
            return bool(result.value)
        finally:
            self._kernel32.CloseHandle(process_handle)

    def memory_peaks(self) -> tuple[int, int]:
        if self._handle is None:
            raise BrokerError("job_closed")
        query_information = self._kernel32.QueryInformationJobObject
        query_information.argtypes = (
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.POINTER(ctypes.c_uint32),
        )
        query_information.restype = ctypes.c_int
        information = _ExtendedLimitInformation()
        returned = ctypes.c_uint32(0)
        if not query_information(
            self._handle,
            self._JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
            ctypes.byref(information),
            ctypes.sizeof(information),
            ctypes.byref(returned),
        ):
            raise BrokerError("job_accounting_query_failed")
        return (
            int(information.peak_process_memory_used),
            int(information.peak_job_memory_used),
        )

    def close(self) -> None:
        handle = self._handle
        self._handle = None
        if handle is not None:
            self._kernel32.CloseHandle(handle)

    def __enter__(self) -> WindowsJobObject:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()


@dataclass(frozen=True, slots=True)
class BrokerSupervisorConfig:
    broker_dll: Path
    dotnet_executable: Path | None = None
    key_path: Path | None = None
    startup_timeout_seconds: float = 10.0
    shutdown_timeout_seconds: float = 5.0

    def validate(self) -> Path:
        if not self.broker_dll.is_file():
            raise FileNotFoundError(f"broker DLL not found: {self.broker_dll}")
        if not 0 < self.startup_timeout_seconds <= 60:
            raise ValueError("broker startup timeout must be between 0 and 60 seconds")
        if not 0 < self.shutdown_timeout_seconds <= 30:
            raise ValueError("broker shutdown timeout must be between 0 and 30 seconds")
        executable = self.dotnet_executable
        if executable is None:
            discovered = shutil.which("dotnet")
            if discovered is None:
                raise FileNotFoundError("dotnet executable was not found")
            executable = Path(discovered)
        if not executable.is_file():
            raise FileNotFoundError(f"dotnet executable not found: {executable}")
        return executable


class BrokerSupervisor(AbstractContextManager["BrokerSupervisor"]):
    def __init__(
        self,
        config: BrokerSupervisorConfig,
        *,
        admission: ResourceAdmissionPolicy | None = None,
        memory_governor: MemoryGovernor | None = None,
        worker_profile_name: str = "windows-broker",
    ) -> None:
        self.config = config
        self.admission = admission or ResourceAdmissionPolicy()
        self.memory_governor = memory_governor
        self.worker_profile_name = worker_profile_name
        self._process: subprocess.Popen[bytes] | None = None
        self._job: WindowsJobObject | None = None
        self._memory_lease: MemoryLease | None = None
        self.pipe_name: str | None = None
        self.health: BrokerResponse | None = None

    @property
    def process_id(self) -> int | None:
        return self._process.pid if self._process is not None else None

    def start(self) -> BrokerResponse:
        if self._process is not None:
            raise BrokerError("broker_already_running")
        lease: MemoryLease | None = None
        if self.memory_governor is None:
            decision = self.admission.evaluate()
            if not decision.allowed:
                raise BrokerError("broker_resource_admission_denied")
        else:
            lease = self.memory_governor.acquire(self.worker_profile_name)
        try:
            dotnet = self.config.validate()
            pipe_name = f"jarvis-windows-broker-{uuid4().hex}"
            creation_flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
            command = [
                str(dotnet),
                str(self.config.broker_dll.resolve()),
                "--pipe-name",
                pipe_name,
            ]
            if self.config.key_path is not None:
                self.config.key_path.parent.mkdir(parents=True, exist_ok=True)
                command.extend(("--key-path", str(self.config.key_path.resolve())))
            process = subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                shell=False,
                creationflags=creation_flags,
            )
            if self.memory_governor is not None:
                profile = self.memory_governor.config.profiles[self.worker_profile_name]
                job = WindowsJobObject(
                    process_memory_limit_bytes=profile.hard_process_limit_bytes,
                    job_memory_limit_bytes=profile.hard_job_limit_bytes,
                    active_process_limit=profile.active_process_limit,
                    allow_breakaway=True,
                )
            else:
                # Broker-launched user applications must be able to leave the broker's
                # kill-on-close job. Inference worker jobs default to no breakaway.
                job = WindowsJobObject(allow_breakaway=True)
        except Exception:
            if lease is not None:
                lease.release()
            raise
        try:
            job.assign_pid(process.pid)
            deadline = time.monotonic() + self.config.startup_timeout_seconds
            last_error: BrokerError | None = None
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise BrokerError("broker_startup_exit")
                remaining = deadline - time.monotonic()
                try:
                    health = BrokerClient(
                        pipe_name,
                        timeout_seconds=max(0.001, remaining),
                    ).health()
                    self._process = process
                    self._job = job
                    self._memory_lease = lease
                    self.pipe_name = pipe_name
                    self.health = health
                    return health
                except BrokerError as error:
                    last_error = error
                    if error.code not in {"broker_unavailable", "broker_connect_timeout"}:
                        raise
                    time.sleep(min(0.05, max(0.0, deadline - time.monotonic())))
            raise BrokerError(
                last_error.code if last_error is not None else "broker_startup_timeout"
            )
        except Exception:
            job.close()
            try:
                process.wait(timeout=self.config.shutdown_timeout_seconds)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=self.config.shutdown_timeout_seconds)
            if lease is not None:
                lease.release()
            raise

    def close(self) -> None:
        process = self._process
        job = self._job
        lease = self._memory_lease
        self._process = None
        self._job = None
        self._memory_lease = None
        self.pipe_name = None
        self.health = None
        if job is not None:
            job.close()
        if process is not None and process.poll() is None:
            try:
                process.wait(timeout=self.config.shutdown_timeout_seconds)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=self.config.shutdown_timeout_seconds)
        if lease is not None:
            lease.release()

    def __enter__(self) -> BrokerSupervisor:
        self.start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()


__all__ = [
    "BrokerClient",
    "BrokerError",
    "BrokerResponse",
    "BrokerSupervisor",
    "BrokerSupervisorConfig",
    "ResourceAdmissionDecision",
    "ResourceAdmissionPolicy",
    "WindowsJobObject",
]
