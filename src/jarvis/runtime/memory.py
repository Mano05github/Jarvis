"""Fail-closed memory admission and pressure planning for Jarvis workers."""

from __future__ import annotations

import math
import os
import threading
import time
import tomllib
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import psutil  # type: ignore[import-untyped]
from pydantic import BaseModel, ConfigDict, Field

_MIB = 1024**2


class MemoryConfigurationError(ValueError):
    """Raised when the memory policy or a worker profile is unsafe."""


class MemoryAdmissionError(RuntimeError):
    """Raised when a worker cannot safely receive a memory lease."""

    def __init__(self, decision: MemoryAdmissionDecision) -> None:
        self.decision = decision
        super().__init__(decision.reason)


class MemoryPressure(StrEnum):
    NORMAL = "normal"
    SOFT = "soft_pressure"
    HARD = "hard_pressure"
    EMERGENCY = "emergency"


class SystemMemorySnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    available_physical_bytes: int = Field(ge=0)
    total_physical_bytes: int = Field(gt=0)
    commit_used_bytes: int = Field(ge=0)
    commit_limit_bytes: int = Field(gt=0)
    captured_monotonic: float = Field(ge=0)

    @property
    def commit_headroom_bytes(self) -> int:
        return max(0, self.commit_limit_bytes - self.commit_used_bytes)


@dataclass(frozen=True, slots=True)
class MemoryPolicy:
    protected_floor_bytes: int
    soft_floor_bytes: int
    emergency_floor_bytes: int
    commit_reserve_bytes: int
    safety_multiplier: float
    maximum_heavy_workers: int
    queue_limit: int
    queue_timeout_seconds: float
    monitor_interval_seconds: float
    recovery_hysteresis_seconds: float

    def __post_init__(self) -> None:
        byte_values = (
            self.protected_floor_bytes,
            self.soft_floor_bytes,
            self.emergency_floor_bytes,
            self.commit_reserve_bytes,
        )
        if any(value <= 0 for value in byte_values):
            raise MemoryConfigurationError("memory policy byte values must be positive")
        if not self.soft_floor_bytes > self.protected_floor_bytes:
            raise MemoryConfigurationError("soft floor must exceed protected floor")
        if not self.protected_floor_bytes > self.emergency_floor_bytes:
            raise MemoryConfigurationError("protected floor must exceed emergency floor")
        if not 1.0 <= self.safety_multiplier <= 3.0:
            raise MemoryConfigurationError("safety multiplier must be between 1 and 3")
        if self.maximum_heavy_workers <= 0:
            raise MemoryConfigurationError("maximum heavy workers must be positive")
        if self.queue_limit < 0:
            raise MemoryConfigurationError("queue limit cannot be negative")
        time_values = (
            self.queue_timeout_seconds,
            self.monitor_interval_seconds,
            self.recovery_hysteresis_seconds,
        )
        if any(value <= 0 for value in time_values):
            raise MemoryConfigurationError("memory policy durations must be positive")


@dataclass(frozen=True, slots=True)
class WorkerMemoryProfile:
    name: str
    certified: bool
    peak_private_bytes: int
    hard_process_limit_bytes: int
    hard_job_limit_bytes: int
    active_process_limit: int
    heavy: bool
    evictable: bool
    eviction_rank: int
    idle_timeout_seconds: float

    def __post_init__(self) -> None:
        if not self.name or len(self.name) > 64:
            raise MemoryConfigurationError("worker profile name is invalid")
        byte_values = (
            self.peak_private_bytes,
            self.hard_process_limit_bytes,
            self.hard_job_limit_bytes,
        )
        if any(value <= 0 for value in byte_values):
            raise MemoryConfigurationError("worker memory limits must be positive")
        if self.hard_process_limit_bytes > self.hard_job_limit_bytes:
            raise MemoryConfigurationError("process limit cannot exceed job limit")
        if self.active_process_limit <= 0:
            raise MemoryConfigurationError("active process limit must be positive")
        if self.eviction_rank < 0:
            raise MemoryConfigurationError("eviction rank cannot be negative")
        if self.idle_timeout_seconds <= 0:
            raise MemoryConfigurationError("idle timeout must be positive")

    def reservation_bytes(self, multiplier: float) -> int:
        reservation = math.ceil(self.peak_private_bytes * multiplier)
        if reservation > self.hard_job_limit_bytes:
            raise MemoryConfigurationError(
                f"worker {self.name!r} hard job limit is below its guarded reservation"
            )
        return reservation


@dataclass(frozen=True, slots=True)
class MemoryRuntimeConfig:
    policy: MemoryPolicy
    profiles: Mapping[str, WorkerMemoryProfile]

    def __post_init__(self) -> None:
        if not self.profiles:
            raise MemoryConfigurationError("at least one worker profile is required")
        for name, profile in self.profiles.items():
            if name != profile.name:
                raise MemoryConfigurationError("worker profile key and name differ")
            profile.reservation_bytes(self.policy.safety_multiplier)


class MemoryAdmissionDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    allowed: bool
    worker_name: str
    reason: str
    pressure: MemoryPressure
    requested_bytes: int = Field(ge=0)
    unrealized_reserved_bytes: int = Field(ge=0)
    physical_headroom_bytes: int
    commit_headroom_bytes: int


class MemoryPressureAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    pressure: MemoryPressure
    available_physical_bytes: int = Field(ge=0)
    commit_headroom_bytes: int = Field(ge=0)
    eviction_lease_ids: tuple[UUID, ...] = ()


@dataclass(slots=True)
class _LeaseRecord:
    lease_id: UUID
    worker_name: str
    reservation_bytes: int
    observed_private_bytes: int
    acquired_monotonic: float

    @property
    def unrealized_bytes(self) -> int:
        return max(0, self.reservation_bytes - self.observed_private_bytes)


class MemoryLease:
    """A releasable claim on memory governed by a ``MemoryGovernor``."""

    def __init__(
        self,
        governor: MemoryGovernor,
        lease_id: UUID,
        worker_name: str,
        reservation_bytes: int,
    ) -> None:
        self._governor = governor
        self.lease_id = lease_id
        self.worker_name = worker_name
        self.reservation_bytes = reservation_bytes
        self._released = False

    @property
    def released(self) -> bool:
        return self._released

    def update_observed_private_bytes(self, observed_bytes: int) -> None:
        if self._released:
            raise MemoryAdmissionError(self._governor.released_lease_decision(self.worker_name))
        self._governor.update_observed(self.lease_id, observed_bytes)

    def release(self) -> None:
        if not self._released:
            self._governor.release(self.lease_id)
            self._released = True

    def __enter__(self) -> MemoryLease:
        return self

    def __exit__(self, *_args: object) -> None:
        self.release()


SnapshotProvider = Callable[[], SystemMemorySnapshot]


class MemoryGovernor:
    """Atomically admits workers without double-counting resident memory."""

    def __init__(
        self,
        config: MemoryRuntimeConfig,
        *,
        snapshot_provider: SnapshotProvider | None = None,
    ) -> None:
        self.config = config
        self._snapshot_provider = snapshot_provider or system_memory_snapshot
        self._lock = threading.RLock()
        self._leases: dict[UUID, _LeaseRecord] = {}

    @property
    def active_lease_count(self) -> int:
        with self._lock:
            return len(self._leases)

    def acquire(
        self,
        worker_name: str,
        *,
        observed_private_bytes: int = 0,
    ) -> MemoryLease:
        return self._acquire(
            worker_name,
            observed_private_bytes=observed_private_bytes,
            allow_uncertified=False,
        )

    def acquire_for_certification(
        self,
        worker_name: str,
        *,
        observed_private_bytes: int = 0,
    ) -> MemoryLease:
        """Admit a provisional profile only inside a capped certification run."""

        return self._acquire(
            worker_name,
            observed_private_bytes=observed_private_bytes,
            allow_uncertified=True,
        )

    def _acquire(
        self,
        worker_name: str,
        *,
        observed_private_bytes: int,
        allow_uncertified: bool,
    ) -> MemoryLease:
        if observed_private_bytes < 0:
            raise ValueError("observed private memory cannot be negative")
        with self._lock:
            snapshot = self._snapshot_provider()
            decision = self._evaluate_locked(
                worker_name,
                snapshot=snapshot,
                observed_private_bytes=observed_private_bytes,
                allow_uncertified=allow_uncertified,
            )
            if not decision.allowed:
                raise MemoryAdmissionError(decision)
            profile = self.config.profiles[worker_name]
            reservation = profile.reservation_bytes(self.config.policy.safety_multiplier)
            lease_id = uuid4()
            self._leases[lease_id] = _LeaseRecord(
                lease_id=lease_id,
                worker_name=worker_name,
                reservation_bytes=reservation,
                observed_private_bytes=observed_private_bytes,
                acquired_monotonic=time.monotonic(),
            )
            return MemoryLease(self, lease_id, worker_name, reservation)

    def evaluate(self, worker_name: str) -> MemoryAdmissionDecision:
        with self._lock:
            return self._evaluate_locked(
                worker_name,
                snapshot=self._snapshot_provider(),
                observed_private_bytes=0,
                allow_uncertified=False,
            )

    def _evaluate_locked(
        self,
        worker_name: str,
        *,
        snapshot: SystemMemorySnapshot,
        observed_private_bytes: int,
        allow_uncertified: bool,
    ) -> MemoryAdmissionDecision:
        policy = self.config.policy
        pressure = classify_pressure(policy, snapshot)
        profile = self.config.profiles.get(worker_name)
        unrealized = sum(record.unrealized_bytes for record in self._leases.values())
        physical_headroom = snapshot.available_physical_bytes - policy.protected_floor_bytes
        commit_headroom = snapshot.commit_headroom_bytes - policy.commit_reserve_bytes
        if profile is None:
            return _decision(
                False,
                worker_name,
                "worker_profile_missing",
                pressure,
                0,
                unrealized,
                physical_headroom,
                commit_headroom,
            )
        requested = profile.reservation_bytes(policy.safety_multiplier)
        if not profile.certified and not allow_uncertified:
            return _decision(
                False,
                worker_name,
                "worker_profile_uncertified",
                pressure,
                requested,
                unrealized,
                physical_headroom,
                commit_headroom,
            )
        if pressure in {MemoryPressure.HARD, MemoryPressure.EMERGENCY}:
            return _decision(
                False,
                worker_name,
                "memory_pressure_blocks_start",
                pressure,
                requested,
                unrealized,
                physical_headroom,
                commit_headroom,
            )
        heavy_count = sum(
            int(self.config.profiles[item.worker_name].heavy) for item in self._leases.values()
        )
        if profile.heavy and heavy_count >= policy.maximum_heavy_workers:
            return _decision(
                False,
                worker_name,
                "heavy_worker_limit_reached",
                pressure,
                requested,
                unrealized,
                physical_headroom,
                commit_headroom,
            )
        new_unrealized = max(0, requested - observed_private_bytes)
        total_unrealized = unrealized + new_unrealized
        if total_unrealized > physical_headroom:
            return _decision(
                False,
                worker_name,
                "insufficient_physical_headroom",
                pressure,
                requested,
                unrealized,
                physical_headroom,
                commit_headroom,
            )
        if total_unrealized > commit_headroom:
            return _decision(
                False,
                worker_name,
                "insufficient_commit_headroom",
                pressure,
                requested,
                unrealized,
                physical_headroom,
                commit_headroom,
            )
        return _decision(
            True,
            worker_name,
            "admitted",
            pressure,
            requested,
            unrealized,
            physical_headroom,
            commit_headroom,
        )

    def update_observed(self, lease_id: UUID, observed_private_bytes: int) -> None:
        if observed_private_bytes < 0:
            raise ValueError("observed private memory cannot be negative")
        with self._lock:
            try:
                record = self._leases[lease_id]
            except KeyError as error:
                raise KeyError("memory lease is not active") from error
            record.observed_private_bytes = observed_private_bytes

    def release(self, lease_id: UUID) -> None:
        with self._lock:
            self._leases.pop(lease_id, None)

    def assess_pressure(self) -> MemoryPressureAssessment:
        with self._lock:
            snapshot = self._snapshot_provider()
            pressure = classify_pressure(self.config.policy, snapshot)
            victims: tuple[UUID, ...] = ()
            if pressure in {MemoryPressure.HARD, MemoryPressure.EMERGENCY}:
                candidates = (
                    record
                    for record in self._leases.values()
                    if self.config.profiles[record.worker_name].evictable
                )
                victims = tuple(
                    record.lease_id
                    for record in sorted(
                        candidates,
                        key=lambda item: (
                            self.config.profiles[item.worker_name].eviction_rank,
                            -item.reservation_bytes,
                            item.acquired_monotonic,
                        ),
                    )
                )
            return MemoryPressureAssessment(
                pressure=pressure,
                available_physical_bytes=snapshot.available_physical_bytes,
                commit_headroom_bytes=snapshot.commit_headroom_bytes,
                eviction_lease_ids=victims,
            )

    def released_lease_decision(self, worker_name: str) -> MemoryAdmissionDecision:
        snapshot = self._snapshot_provider()
        return _decision(
            False,
            worker_name,
            "memory_lease_released",
            classify_pressure(self.config.policy, snapshot),
            0,
            0,
            snapshot.available_physical_bytes - self.config.policy.protected_floor_bytes,
            snapshot.commit_headroom_bytes - self.config.policy.commit_reserve_bytes,
        )


def _decision(
    allowed: bool,
    worker_name: str,
    reason: str,
    pressure: MemoryPressure,
    requested_bytes: int,
    unrealized_reserved_bytes: int,
    physical_headroom_bytes: int,
    commit_headroom_bytes: int,
) -> MemoryAdmissionDecision:
    return MemoryAdmissionDecision(
        allowed=allowed,
        worker_name=worker_name,
        reason=reason,
        pressure=pressure,
        requested_bytes=requested_bytes,
        unrealized_reserved_bytes=unrealized_reserved_bytes,
        physical_headroom_bytes=physical_headroom_bytes,
        commit_headroom_bytes=commit_headroom_bytes,
    )


def classify_pressure(policy: MemoryPolicy, snapshot: SystemMemorySnapshot) -> MemoryPressure:
    available = snapshot.available_physical_bytes
    commit = snapshot.commit_headroom_bytes
    if available < policy.emergency_floor_bytes or commit < policy.commit_reserve_bytes:
        return MemoryPressure.EMERGENCY
    if available < policy.protected_floor_bytes:
        return MemoryPressure.HARD
    if available < policy.soft_floor_bytes:
        return MemoryPressure.SOFT
    return MemoryPressure.NORMAL


def system_memory_snapshot() -> SystemMemorySnapshot:
    """Read conservative physical and commit estimates without treating pagefile as RAM."""

    memory = psutil.virtual_memory()
    swap = psutil.swap_memory()
    # psutil does not expose Windows commit directly. The fallback is conservative:
    # used physical plus used pagefile cannot overstate safe commit headroom.
    commit_limit = int(memory.total + swap.total)
    commit_used = int(memory.total - memory.available + swap.used)
    if os.name == "nt":
        native = _windows_commit_snapshot()
        if native is not None:
            commit_used, commit_limit = native
    return SystemMemorySnapshot(
        available_physical_bytes=int(memory.available),
        total_physical_bytes=int(memory.total),
        commit_used_bytes=commit_used,
        commit_limit_bytes=max(1, commit_limit),
        captured_monotonic=time.monotonic(),
    )


def _windows_commit_snapshot() -> tuple[int, int] | None:
    import ctypes

    class PerformanceInformation(ctypes.Structure):
        _fields_ = [
            ("cb", ctypes.c_uint32),
            ("commit_total", ctypes.c_size_t),
            ("commit_limit", ctypes.c_size_t),
            ("commit_peak", ctypes.c_size_t),
            ("physical_total", ctypes.c_size_t),
            ("physical_available", ctypes.c_size_t),
            ("system_cache", ctypes.c_size_t),
            ("kernel_total", ctypes.c_size_t),
            ("kernel_paged", ctypes.c_size_t),
            ("kernel_nonpaged", ctypes.c_size_t),
            ("page_size", ctypes.c_size_t),
            ("handle_count", ctypes.c_uint32),
            ("process_count", ctypes.c_uint32),
            ("thread_count", ctypes.c_uint32),
        ]

    try:
        information = PerformanceInformation()
        information.cb = ctypes.sizeof(information)
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        get_performance_info = psapi.GetPerformanceInfo
        get_performance_info.argtypes = (
            ctypes.POINTER(PerformanceInformation),
            ctypes.c_uint32,
        )
        get_performance_info.restype = ctypes.c_int
        if not get_performance_info(ctypes.byref(information), information.cb):
            return None
        return (
            int(information.commit_total * information.page_size),
            int(information.commit_limit * information.page_size),
        )
    except (AttributeError, OSError):
        return None


def load_memory_runtime_config(path: Path) -> MemoryRuntimeConfig:
    try:
        payload = tomllib.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise MemoryConfigurationError(f"memory config could not be read: {path}") from error
    try:
        _require_keys(payload, {"schema_version", "policy", "workers"}, "root")
        if payload["schema_version"] != "1.0":
            raise MemoryConfigurationError("unsupported memory config schema version")
        policy_data = _mapping(payload, "policy")
        _require_keys(
            policy_data,
            {
                "protected_floor_mib",
                "soft_floor_mib",
                "emergency_floor_mib",
                "commit_reserve_mib",
                "safety_multiplier",
                "maximum_heavy_workers",
                "queue_limit",
                "queue_timeout_seconds",
                "monitor_interval_seconds",
                "recovery_hysteresis_seconds",
            },
            "policy",
        )
        policy = MemoryPolicy(
            protected_floor_bytes=_mib(policy_data, "protected_floor_mib"),
            soft_floor_bytes=_mib(policy_data, "soft_floor_mib"),
            emergency_floor_bytes=_mib(policy_data, "emergency_floor_mib"),
            commit_reserve_bytes=_mib(policy_data, "commit_reserve_mib"),
            safety_multiplier=_number(policy_data, "safety_multiplier"),
            maximum_heavy_workers=_integer(policy_data, "maximum_heavy_workers"),
            queue_limit=_integer(policy_data, "queue_limit", minimum=0),
            queue_timeout_seconds=_number(policy_data, "queue_timeout_seconds"),
            monitor_interval_seconds=_number(policy_data, "monitor_interval_seconds"),
            recovery_hysteresis_seconds=float(_number(policy_data, "recovery_hysteresis_seconds")),
        )
        raw_workers = payload["workers"]
        if not isinstance(raw_workers, list):
            raise TypeError("workers must be an array")
        profiles: dict[str, WorkerMemoryProfile] = {}
        for raw in raw_workers:
            if not isinstance(raw, dict):
                raise TypeError("worker profile must be a table")
            _require_keys(
                raw,
                {
                    "name",
                    "certified",
                    "peak_private_mib",
                    "hard_process_limit_mib",
                    "hard_job_limit_mib",
                    "active_process_limit",
                    "heavy",
                    "evictable",
                    "eviction_rank",
                    "idle_timeout_seconds",
                },
                "worker",
            )
            if not isinstance(raw["name"], str):
                raise TypeError("worker name must be a string")
            name = str(raw["name"])
            if name in profiles:
                raise MemoryConfigurationError(f"duplicate worker profile: {name}")
            profiles[name] = WorkerMemoryProfile(
                name=name,
                certified=_boolean(raw, "certified"),
                peak_private_bytes=_mib(raw, "peak_private_mib"),
                hard_process_limit_bytes=_mib(raw, "hard_process_limit_mib"),
                hard_job_limit_bytes=_mib(raw, "hard_job_limit_mib"),
                active_process_limit=_integer(raw, "active_process_limit"),
                heavy=_boolean(raw, "heavy"),
                evictable=_boolean(raw, "evictable"),
                eviction_rank=_integer(raw, "eviction_rank", minimum=0),
                idle_timeout_seconds=_number(raw, "idle_timeout_seconds"),
            )
        return MemoryRuntimeConfig(policy=policy, profiles=profiles)
    except (KeyError, TypeError, ValueError) as error:
        if isinstance(error, MemoryConfigurationError):
            raise
        raise MemoryConfigurationError("memory config has invalid fields") from error


def _mapping(payload: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = payload[key]
    if not isinstance(value, dict):
        raise TypeError(f"{key} must be a table")
    return value


def _mib(payload: Mapping[str, Any], key: str) -> int:
    value = payload[key]
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{key} must be a positive integer")
    return int(value) * _MIB


def _boolean(payload: Mapping[str, Any], key: str) -> bool:
    value = payload[key]
    if not isinstance(value, bool):
        raise TypeError(f"{key} must be a boolean")
    return value


def _integer(payload: Mapping[str, Any], key: str, *, minimum: int = 1) -> int:
    value = payload[key]
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{key} must be an integer >= {minimum}")
    return int(value)


def _number(payload: Mapping[str, Any], key: str) -> float:
    value = payload[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise ValueError(f"{key} must be a positive number")
    return float(value)


def _require_keys(payload: Mapping[str, Any], expected: set[str], section: str) -> None:
    actual = set(payload)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise MemoryConfigurationError(
            f"memory config {section} keys differ; missing={missing}, extra={extra}"
        )


__all__ = [
    "MemoryAdmissionDecision",
    "MemoryAdmissionError",
    "MemoryConfigurationError",
    "MemoryGovernor",
    "MemoryLease",
    "MemoryPolicy",
    "MemoryPressure",
    "MemoryPressureAssessment",
    "MemoryRuntimeConfig",
    "SystemMemorySnapshot",
    "WorkerMemoryProfile",
    "classify_pressure",
    "load_memory_runtime_config",
    "system_memory_snapshot",
]
