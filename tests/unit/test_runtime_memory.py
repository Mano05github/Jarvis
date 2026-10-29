from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest

from jarvis.runtime.memory import (
    MemoryAdmissionError,
    MemoryConfigurationError,
    MemoryGovernor,
    MemoryPolicy,
    MemoryPressure,
    MemoryRuntimeConfig,
    SystemMemorySnapshot,
    WorkerMemoryProfile,
    classify_pressure,
    load_memory_runtime_config,
)

MIB = 1024**2
GIB = 1024**3
PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _policy() -> MemoryPolicy:
    return MemoryPolicy(
        protected_floor_bytes=4 * GIB,
        soft_floor_bytes=5 * GIB,
        emergency_floor_bytes=3_584 * MIB,
        commit_reserve_bytes=GIB,
        safety_multiplier=1.25,
        maximum_heavy_workers=1,
        queue_limit=2,
        queue_timeout_seconds=15,
        monitor_interval_seconds=0.5,
        recovery_hysteresis_seconds=30,
    )


def _profile(
    name: str,
    *,
    peak_gib: float = 2,
    certified: bool = True,
    heavy: bool = True,
    eviction_rank: int = 10,
    evictable: bool = True,
) -> WorkerMemoryProfile:
    peak = int(peak_gib * GIB)
    hard = int(peak * 1.5)
    return WorkerMemoryProfile(
        name=name,
        certified=certified,
        peak_private_bytes=peak,
        hard_process_limit_bytes=hard,
        hard_job_limit_bytes=hard,
        active_process_limit=1,
        heavy=heavy,
        evictable=evictable,
        eviction_rank=eviction_rank,
        idle_timeout_seconds=60,
    )


def _snapshot(
    available_gib: float = 8,
    *,
    commit_headroom_gib: float = 10,
) -> SystemMemorySnapshot:
    total = 16 * GIB
    limit = 24 * GIB
    return SystemMemorySnapshot(
        available_physical_bytes=int(available_gib * GIB),
        total_physical_bytes=total,
        commit_used_bytes=limit - int(commit_headroom_gib * GIB),
        commit_limit_bytes=limit,
        captured_monotonic=1,
    )


def _governor(
    snapshot: SystemMemorySnapshot,
    *profiles: WorkerMemoryProfile,
) -> MemoryGovernor:
    config = MemoryRuntimeConfig(
        policy=_policy(), profiles={profile.name: profile for profile in profiles}
    )
    return MemoryGovernor(config, snapshot_provider=lambda: snapshot)


@pytest.mark.parametrize(
    ("available_gib", "commit_gib", "expected"),
    [
        (6, 8, MemoryPressure.NORMAL),
        (4.5, 8, MemoryPressure.SOFT),
        (3.75, 8, MemoryPressure.HARD),
        (3.4, 8, MemoryPressure.EMERGENCY),
        (8, 0.5, MemoryPressure.EMERGENCY),
    ],
)
def test_pressure_classification(
    available_gib: float, commit_gib: float, expected: MemoryPressure
) -> None:
    assert (
        classify_pressure(_policy(), _snapshot(available_gib, commit_headroom_gib=commit_gib))
        == expected
    )


def test_config_loads_certified_and_provisional_profiles() -> None:
    config = load_memory_runtime_config(PROJECT_ROOT / "config" / "runtime" / "memory-policy.toml")

    assert config.policy.protected_floor_bytes == 4 * GIB
    assert config.profiles["windows-broker"].certified is True
    native_stt = config.profiles["native-stt-candidate"]
    assert native_stt.certified is False
    assert native_stt.peak_private_bytes == 512 * MIB
    assert native_stt.hard_process_limit_bytes == 640 * MIB
    assert native_stt.hard_job_limit_bytes == 640 * MIB
    assert native_stt.reservation_bytes(1.25) == 640 * MIB
    assert config.profiles["qwen-local"].certified is False
    assert config.profiles["qwen-local"].reservation_bytes(1.25) == 6_800 * MIB


def test_missing_and_uncertified_profiles_fail_closed() -> None:
    provisional = _profile("provisional", certified=False)
    governor = _governor(_snapshot(), provisional)

    assert governor.evaluate("missing").reason == "worker_profile_missing"
    with pytest.raises(MemoryAdmissionError) as caught:
        governor.acquire("provisional")
    assert caught.value.decision.reason == "worker_profile_uncertified"
    assert governor.active_lease_count == 0

    certification_lease = governor.acquire_for_certification("provisional")
    assert governor.active_lease_count == 1
    certification_lease.release()
    assert governor.active_lease_count == 0


def test_atomic_lease_blocks_second_heavy_worker_and_releases() -> None:
    first = _profile("llm")
    second = _profile("tts")
    governor = _governor(_snapshot(), first, second)

    lease = governor.acquire("llm")
    assert governor.active_lease_count == 1
    with pytest.raises(MemoryAdmissionError) as caught:
        governor.acquire("tts")
    assert caught.value.decision.reason == "heavy_worker_limit_reached"

    lease.release()
    assert governor.active_lease_count == 0
    with governor.acquire("tts") as replacement:
        assert replacement.released is False
    assert replacement.released is True


def test_concurrent_heavy_admission_is_atomic() -> None:
    governor = _governor(_snapshot(), _profile("llm"))

    def attempt() -> bool:
        try:
            governor.acquire("llm")
        except MemoryAdmissionError:
            return False
        return True

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _index: attempt(), range(8)))

    assert results.count(True) == 1
    assert governor.active_lease_count == 1


def test_resident_memory_is_not_double_counted() -> None:
    light = _profile("broker", peak_gib=1, heavy=False, evictable=False)
    governor = _governor(_snapshot(6), light)

    lease = governor.acquire("broker")
    # A 1.25 GiB lease initially contributes its full unrealized reservation.
    assert governor.evaluate("broker").unrealized_reserved_bytes == int(1.25 * GIB)
    lease.update_observed_private_bytes(GIB)
    # Available physical already reflects the resident 1 GiB, so only 0.25 GiB remains.
    assert governor.evaluate("broker").unrealized_reserved_bytes == int(0.25 * GIB)


@pytest.mark.parametrize(
    ("snapshot", "reason"),
    [
        (_snapshot(7, commit_headroom_gib=2), "insufficient_commit_headroom"),
        (_snapshot(5.5, commit_headroom_gib=8), "insufficient_physical_headroom"),
        (_snapshot(3.75, commit_headroom_gib=8), "memory_pressure_blocks_start"),
    ],
)
def test_admission_enforces_both_headrooms(snapshot: SystemMemorySnapshot, reason: str) -> None:
    governor = _governor(snapshot, _profile("tts"))
    with pytest.raises(MemoryAdmissionError) as caught:
        governor.acquire("tts")
    assert caught.value.decision.reason == reason


def test_pressure_assessment_orders_only_evictable_workers() -> None:
    llm = _profile("llm", peak_gib=1, heavy=False, eviction_rank=10)
    tts = _profile("tts", peak_gib=1, heavy=False, eviction_rank=20)
    broker = _profile("broker", peak_gib=0.25, heavy=False, eviction_rank=100, evictable=False)
    current = [_snapshot(8)]
    config = MemoryRuntimeConfig(
        policy=_policy(), profiles={item.name: item for item in (llm, tts, broker)}
    )
    governor = MemoryGovernor(config, snapshot_provider=lambda: current[0])
    llm_lease = governor.acquire("llm")
    tts_lease = governor.acquire("tts")
    governor.acquire("broker")

    current[0] = _snapshot(3.75)
    assessment = governor.assess_pressure()
    assert assessment.pressure is MemoryPressure.HARD
    assert assessment.eviction_lease_ids == (llm_lease.lease_id, tts_lease.lease_id)


def test_invalid_policy_profile_and_config_are_rejected(tmp_path: Path) -> None:
    with pytest.raises(MemoryConfigurationError, match="soft floor"):
        MemoryPolicy(
            protected_floor_bytes=4,
            soft_floor_bytes=4,
            emergency_floor_bytes=3,
            commit_reserve_bytes=1,
            safety_multiplier=1.25,
            maximum_heavy_workers=1,
            queue_limit=2,
            queue_timeout_seconds=1,
            monitor_interval_seconds=1,
            recovery_hysteresis_seconds=1,
        )
    with pytest.raises(MemoryConfigurationError, match="below"):
        _profile("bad", peak_gib=2).reservation_bytes(2)

    invalid = tmp_path / "invalid.toml"
    invalid.write_text("[policy\n", encoding="utf-8")
    with pytest.raises(MemoryConfigurationError, match="could not be read"):
        load_memory_runtime_config(invalid)

    unsafe = tmp_path / "unsafe.toml"
    unsafe.write_text(
        "schema_version='1.0'\n[policy]\nunexpected=1\nworkers=[]\n",
        encoding="utf-8",
    )
    with pytest.raises(MemoryConfigurationError, match="root keys differ"):
        load_memory_runtime_config(unsafe)


def test_released_lease_cannot_be_updated() -> None:
    governor = _governor(_snapshot(), _profile("tts"))
    lease = governor.acquire("tts")
    lease.release()
    lease.release()
    with pytest.raises(MemoryAdmissionError) as caught:
        lease.update_observed_private_bytes(1)
    assert caught.value.decision.reason == "memory_lease_released"


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"protected_floor_bytes": 0}, "byte values"),
        ({"emergency_floor_bytes": 5 * GIB}, "protected floor"),
        ({"safety_multiplier": 0.5}, "safety multiplier"),
        ({"maximum_heavy_workers": 0}, "heavy workers"),
        ({"queue_limit": -1}, "queue limit"),
        ({"monitor_interval_seconds": 0}, "durations"),
    ],
)
def test_policy_rejects_each_unsafe_boundary(changes: dict[str, float | int], message: str) -> None:
    with pytest.raises(MemoryConfigurationError, match=message):
        replace(_policy(), **changes)


def test_runtime_config_and_observations_fail_closed() -> None:
    profile = _profile("worker")
    with pytest.raises(MemoryConfigurationError, match="at least one"):
        MemoryRuntimeConfig(policy=_policy(), profiles={})
    with pytest.raises(MemoryConfigurationError, match="key and name"):
        MemoryRuntimeConfig(policy=_policy(), profiles={"different": profile})

    governor = _governor(_snapshot(), profile)
    with pytest.raises(ValueError, match="observed private"):
        governor.acquire("worker", observed_private_bytes=-1)
    with pytest.raises(ValueError, match="observed private"):
        governor.update_observed(uuid4(), -1)
    with pytest.raises(KeyError, match="not active"):
        governor.update_observed(uuid4(), 0)
