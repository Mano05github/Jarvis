import sys

from jarvis.benchmarking.process import ExecutionLimits, run_bounded


def test_run_bounded_captures_tail_and_metrics() -> None:
    result = run_bounded(
        [sys.executable, "-c", "print('abcdefgh')"],
        limits=ExecutionLimits(
            timeout_seconds=5,
            output_bytes=4,
            sample_interval_seconds=0.01,
        ),
    )
    assert result.exit_code == 0
    assert not result.timed_out
    assert "gh" in result.stdout_tail
    assert result.stdout_tail.endswith("\n")
    assert result.output_truncated
    assert result.elapsed_seconds > 0


def test_run_bounded_terminates_timeout() -> None:
    result = run_bounded(
        [sys.executable, "-c", "import time; time.sleep(5)"],
        limits=ExecutionLimits(
            timeout_seconds=0.1,
            output_bytes=1024,
            sample_interval_seconds=0.01,
        ),
    )
    assert result.timed_out
    assert result.elapsed_seconds < 3
