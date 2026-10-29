"""Memory-governed process containment shared by model workers."""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Protocol

from jarvis.runtime.broker import WindowsJobObject
from jarvis.runtime.memory import MemoryGovernor, MemoryLease


class JobContainment(Protocol):
    def assign_pid(self, process_id: int) -> None: ...

    def contains_pid(self, process_id: int) -> bool: ...

    def memory_peaks(self) -> tuple[int, int]: ...

    def close(self) -> None: ...


JobFactory = Callable[..., JobContainment]


class GovernedWorkerSlot:
    """Own one memory lease and one kill-on-close Job Object."""

    def __init__(
        self,
        governor: MemoryGovernor,
        profile_name: str,
        *,
        certification_mode: bool = False,
        job_factory: JobFactory = WindowsJobObject,
    ) -> None:
        self.governor = governor
        self.profile_name = profile_name
        self.certification_mode = certification_mode
        self._job_factory = job_factory
        self._lock = threading.RLock()
        self._lease: MemoryLease | None = None
        self._job: JobContainment | None = None
        self._assigned_pid: int | None = None
        self._verified_pid: int | None = None

    @property
    def active(self) -> bool:
        with self._lock:
            return self._lease is not None

    @property
    def assigned_pid(self) -> int | None:
        with self._lock:
            return self._assigned_pid

    @property
    def containment_verified(self) -> bool:
        with self._lock:
            return self._verified_pid is not None

    def start(self) -> None:
        with self._lock:
            if self._lease is not None:
                raise RuntimeError("worker containment slot is already active")
            profile = self.governor.config.profiles.get(self.profile_name)
            if profile is None:
                # Preserve the governor's structured fail-closed decision.
                self.governor.acquire(self.profile_name)
                raise AssertionError("unreachable")
            lease = (
                self.governor.acquire_for_certification(self.profile_name)
                if self.certification_mode
                else self.governor.acquire(self.profile_name)
            )
            try:
                job = self._job_factory(
                    process_memory_limit_bytes=profile.hard_process_limit_bytes,
                    job_memory_limit_bytes=profile.hard_job_limit_bytes,
                    active_process_limit=profile.active_process_limit,
                    allow_breakaway=False,
                )
            except Exception:
                lease.release()
                raise
            self._lease = lease
            self._job = job

    def assign_pid(self, process_id: int) -> None:
        with self._lock:
            if self._job is None or self._lease is None:
                raise RuntimeError("worker containment slot is not active")
            if self._assigned_pid is not None:
                raise RuntimeError("worker containment slot already has a process")
            self._job.assign_pid(process_id)
            self._assigned_pid = process_id

    def verify_pid(self, process_id: int) -> None:
        with self._lock:
            if self._job is None or self._lease is None:
                raise RuntimeError("worker containment slot is not active")
            if self._assigned_pid != process_id:
                raise RuntimeError("worker process ID is not the assigned process")
            if not self._job.contains_pid(process_id):
                raise RuntimeError("worker process is not contained by the Job Object")
            self._verified_pid = process_id

    def update_observed_private_bytes(self, observed_bytes: int) -> None:
        with self._lock:
            if self._lease is None:
                raise RuntimeError("worker containment slot is not active")
            self._lease.update_observed_private_bytes(observed_bytes)

    def memory_peaks(self) -> tuple[int, int]:
        with self._lock:
            if self._job is None or self._lease is None:
                raise RuntimeError("worker containment slot is not active")
            return self._job.memory_peaks()

    def close(self) -> None:
        with self._lock:
            job = self._job
            lease = self._lease
            self._job = None
            self._lease = None
            self._assigned_pid = None
            self._verified_pid = None
            try:
                if job is not None:
                    job.close()
            finally:
                if lease is not None:
                    lease.release()

    def __enter__(self) -> GovernedWorkerSlot:
        self.start()
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()


__all__ = ["GovernedWorkerSlot", "JobContainment", "JobFactory"]
