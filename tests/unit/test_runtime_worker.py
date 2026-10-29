from __future__ import annotations

from dataclasses import dataclass

import pytest

from jarvis.runtime.memory import (
    MemoryGovernor,
    MemoryPolicy,
    MemoryRuntimeConfig,
    SystemMemorySnapshot,
    WorkerMemoryProfile,
)
from jarvis.runtime.worker import GovernedWorkerSlot

GIB = 1024**3


@dataclass
class FakeJob:
    assigned_pid: int | None = None
    closed: bool = False
    contained: bool = True

    def assign_pid(self, process_id: int) -> None:
        self.assigned_pid = process_id

    def contains_pid(self, process_id: int) -> bool:
        return self.contained and self.assigned_pid == process_id

    def memory_peaks(self) -> tuple[int, int]:
        return (123, 456)

    def close(self) -> None:
        self.closed = True


def governor(*, certified: bool = True) -> MemoryGovernor:
    policy = MemoryPolicy(
        protected_floor_bytes=4 * GIB,
        soft_floor_bytes=5 * GIB,
        emergency_floor_bytes=3 * GIB,
        commit_reserve_bytes=GIB,
        safety_multiplier=1.25,
        maximum_heavy_workers=1,
        queue_limit=2,
        queue_timeout_seconds=15,
        monitor_interval_seconds=0.5,
        recovery_hysteresis_seconds=30,
    )
    profile = WorkerMemoryProfile(
        name="stt",
        certified=certified,
        peak_private_bytes=GIB,
        hard_process_limit_bytes=2 * GIB,
        hard_job_limit_bytes=2 * GIB,
        active_process_limit=1,
        heavy=True,
        evictable=True,
        eviction_rank=30,
        idle_timeout_seconds=60,
    )
    snapshot = SystemMemorySnapshot(
        available_physical_bytes=8 * GIB,
        total_physical_bytes=16 * GIB,
        commit_used_bytes=8 * GIB,
        commit_limit_bytes=24 * GIB,
        captured_monotonic=1,
    )
    return MemoryGovernor(
        MemoryRuntimeConfig(policy=policy, profiles={"stt": profile}),
        snapshot_provider=lambda: snapshot,
    )


def test_slot_owns_job_and_lease_lifecycle() -> None:
    memory = governor()
    jobs: list[FakeJob] = []

    def factory(**_kwargs: object) -> FakeJob:
        job = FakeJob()
        jobs.append(job)
        return job

    slot = GovernedWorkerSlot(memory, "stt", job_factory=factory)
    slot.start()
    slot.assign_pid(123)
    slot.verify_pid(123)
    slot.update_observed_private_bytes(GIB)

    assert slot.active is True
    assert slot.assigned_pid == 123
    assert slot.containment_verified is True
    assert slot.memory_peaks() == (123, 456)
    assert memory.active_lease_count == 1
    slot.close()
    assert jobs[0].closed is True
    assert memory.active_lease_count == 0


def test_slot_certification_and_failure_cleanup() -> None:
    memory = governor(certified=False)
    slot = GovernedWorkerSlot(
        memory,
        "stt",
        certification_mode=True,
        job_factory=lambda **_kwargs: FakeJob(),
    )
    with slot:
        assert slot.active

    def fail(**_kwargs: object) -> FakeJob:
        raise RuntimeError("job failed")

    broken = GovernedWorkerSlot(memory, "stt", certification_mode=True, job_factory=fail)
    with pytest.raises(RuntimeError, match="job failed"):
        broken.start()
    assert memory.active_lease_count == 0


def test_slot_rejects_invalid_state_transitions() -> None:
    memory = governor()
    slot = GovernedWorkerSlot(memory, "stt", job_factory=lambda **_kwargs: FakeJob())
    with pytest.raises(RuntimeError, match="not active"):
        slot.assign_pid(1)
    with pytest.raises(RuntimeError, match="not active"):
        slot.verify_pid(1)
    slot.start()
    with pytest.raises(RuntimeError, match="already active"):
        slot.start()
    slot.assign_pid(1)
    with pytest.raises(RuntimeError, match="already has"):
        slot.assign_pid(2)
    with pytest.raises(RuntimeError, match="not the assigned"):
        slot.verify_pid(2)
    slot.verify_pid(1)
    slot.close()
    with pytest.raises(RuntimeError, match="not active"):
        slot.update_observed_private_bytes(1)


def test_slot_fails_closed_when_job_membership_is_not_verified() -> None:
    memory = governor()
    job = FakeJob(contained=False)
    slot = GovernedWorkerSlot(memory, "stt", job_factory=lambda **_kwargs: job)
    slot.start()
    slot.assign_pid(123)

    with pytest.raises(RuntimeError, match="not contained"):
        slot.verify_pid(123)
    assert slot.containment_verified is False
    slot.close()
    assert memory.active_lease_count == 0


def test_slot_releases_lease_even_if_job_close_fails() -> None:
    memory = governor()

    class BrokenCloseJob(FakeJob):
        def close(self) -> None:
            raise RuntimeError("close failed")

    slot = GovernedWorkerSlot(memory, "stt", job_factory=lambda **_kwargs: BrokenCloseJob())
    slot.start()
    with pytest.raises(RuntimeError, match="close failed"):
        slot.close()
    assert memory.active_lease_count == 0
