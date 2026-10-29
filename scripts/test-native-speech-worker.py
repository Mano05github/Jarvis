from __future__ import annotations

import gc
import hashlib
import queue
import statistics
import struct
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import BinaryIO

import psutil  # type: ignore[import-untyped]

MAGIC = 0x5454534A
VERSION = 1
HEADER_BYTES = 40
MAX_AUDIO_BYTES = 32768
AUTH_LABEL = b"jarvis-stt-start-auth-v1"
SOAK_CYCLES = 100

BOOTSTRAP = 2
START_AUTH = 3
READY = 4
START_SESSION = 5
AUDIO = 6
PARTIAL = 7
FINISH = 8
FINAL = 9
CANCEL = 10
RESET = 11
ERROR = 13
SHUTDOWN = 14

HEADER = struct.Struct("<IHHHHI16sQ")
Frame = tuple[int, bytes, int, bytes]
checks = 0


def check(condition: bool, message: str) -> None:
    global checks
    checks += 1
    if not condition:
        raise AssertionError(message)


def encode_header(
    message_type: int,
    session: bytes,
    sequence: int,
    payload_size: int,
    *,
    magic: int = MAGIC,
    version: int = VERSION,
    header_bytes: int = HEADER_BYTES,
    flags: int = 0,
) -> bytes:
    return HEADER.pack(
        magic,
        version,
        header_bytes,
        message_type,
        flags,
        payload_size,
        session,
        sequence,
    )


def encode(message_type: int, session: bytes, sequence: int, payload: bytes = b"") -> bytes:
    return encode_header(message_type, session, sequence, len(payload)) + payload


def read_exact(stream: BinaryIO, count: int) -> bytes:
    chunks: list[bytes] = []
    remaining = count
    while remaining:
        chunk = stream.read(remaining)
        if not chunk:
            raise EOFError(f"worker closed with {remaining} bytes still expected")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def read_frame(stream: BinaryIO) -> Frame:
    raw_header = read_exact(stream, HEADER_BYTES)
    magic, version, header_bytes, message_type, flags, size, session, sequence = HEADER.unpack(
        raw_header
    )
    check(magic == MAGIC, "bad worker magic")
    check(version == VERSION and header_bytes == HEADER_BYTES, "bad worker version")
    check(flags == 0, "unexpected worker flags")
    check(size <= 65536, "worker payload exceeded protocol limit")
    return message_type, session, sequence, read_exact(stream, size)


def read_frame_timeout(process: subprocess.Popen[bytes], timeout: float = 5.0) -> Frame:
    results: queue.Queue[object] = queue.Queue(maxsize=1)

    def reader() -> None:
        try:
            assert process.stdout is not None
            results.put(read_frame(process.stdout))
        except BaseException as error:  # transported back to the test thread
            results.put(error)

    threading.Thread(target=reader, daemon=True).start()
    try:
        result = results.get(timeout=timeout)
    except queue.Empty as error:
        process.kill()
        process.wait(timeout=5)
        raise TimeoutError("worker response timed out") from error
    if isinstance(result, BaseException):
        raise result
    return result  # type: ignore[return-value]


def start_worker(executable: Path, *arguments: str) -> subprocess.Popen[bytes]:
    return subprocess.Popen(
        [str(executable), *arguments],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def send(process: subprocess.Popen[bytes], frame: bytes) -> None:
    assert process.stdin is not None
    process.stdin.write(frame)
    process.stdin.flush()


def send_fragmented(process: subprocess.Popen[bytes], frame: bytes) -> None:
    for byte in frame:
        send(process, bytes((byte,)))


def bootstrap(process: subprocess.Popen[bytes]) -> tuple[bytes, bytes]:
    message_type, session, sequence, payload = read_frame_timeout(process)
    check(message_type == BOOTSTRAP and sequence == 1, "missing bootstrap")
    check(len(session) == 16 and any(session), "invalid bootstrap session")
    check(len(payload) == 40, "invalid bootstrap payload")
    process_id, capabilities = struct.unpack_from("<II", payload)
    check(process_id == process.pid, "bootstrap PID does not match child")
    check(capabilities & 0x3 == 0x3, "required fake/auth capabilities missing")
    nonce = payload[8:]
    digest = hashlib.sha256(AUTH_LABEL + session + nonce).digest()
    return session, digest


def close_streams(process: subprocess.Popen[bytes]) -> str:
    stderr = ""
    if process.stderr is not None and not process.stderr.closed:
        stderr = process.stderr.read().decode("utf-8", errors="replace")
        process.stderr.close()
    if process.stdout is not None and not process.stdout.closed:
        process.stdout.close()
    return stderr


def finish_process(process: subprocess.Popen[bytes], expected_code: int) -> None:
    if process.stdin is not None and not process.stdin.closed:
        process.stdin.close()
    code = process.wait(timeout=5)
    stderr = close_streams(process)
    check(code == expected_code, f"exit {code}, expected {expected_code}: {stderr}")
    check(not psutil.pid_exists(process.pid), f"worker PID {process.pid} survived exit")


def authorize(process: subprocess.Popen[bytes], session: bytes, digest: bytes) -> None:
    send(process, encode(START_AUTH, session, 1, digest))
    check(read_frame_timeout(process)[:3] == (READY, session, 2), "auth not acknowledged")


def begin_session(process: subprocess.Popen[bytes], session: bytes, sequence: int = 2) -> None:
    send(process, encode(START_SESSION, session, sequence))
    check(
        read_frame_timeout(process)[:3] == (READY, session, 3),
        "session not started",
    )


def expect_error(
    process: subprocess.Popen[bytes],
    session: bytes,
    sequence: int,
    expected_payload: bytes,
) -> None:
    response = read_frame_timeout(process)
    check(response[:3] == (ERROR, session, sequence), "expected worker error frame")
    check(response[3] == expected_payload, "unexpected safe worker error")
    finish_process(process, 3)


def test_full_lifecycle(executable: Path) -> None:
    process = start_worker(executable)
    session, digest = bootstrap(process)
    authorize(process, session, digest)
    begin_session(process, session)
    send(process, encode(AUDIO, session, 3, b"\x00\x00" * 8))
    partial = read_frame_timeout(process)
    check(partial[:3] == (PARTIAL, session, 4), "partial frame mismatch")
    check(partial[3] == b"calculator", "unexpected fake partial")
    send(process, encode(FINISH, session, 4))
    final = read_frame_timeout(process)
    check(final[:3] == (FINAL, session, 5), "final frame mismatch")
    check(final[3] == b"calculator open pannu", "unexpected fake final")
    send(process, encode(RESET, session, 5))
    check(read_frame_timeout(process)[:3] == (READY, session, 6), "reset not acknowledged")
    send(process, encode(START_SESSION, session, 6))
    check(read_frame_timeout(process)[:3] == (READY, session, 7), "restart failed")
    send(process, encode(CANCEL, session, 7))
    check(read_frame_timeout(process)[:3] == (CANCEL, session, 8), "cancel not acknowledged")
    send(process, encode(RESET, session, 8))
    check(read_frame_timeout(process)[:3] == (READY, session, 9), "cancel reset failed")
    send(process, encode(SHUTDOWN, session, 9))
    finish_process(process, 0)


def test_fragmented_and_coalesced_input(executable: Path) -> None:
    process = start_worker(executable)
    session, digest = bootstrap(process)
    send_fragmented(process, encode(START_AUTH, session, 1, digest))
    check(read_frame_timeout(process)[:3] == (READY, session, 2), "fragmented auth failed")
    send(
        process,
        encode(START_SESSION, session, 2) + encode(AUDIO, session, 3, b"\x00\x00" * 4),
    )
    check(read_frame_timeout(process)[:3] == (READY, session, 3), "coalesced start failed")
    partial = read_frame_timeout(process)
    check(partial[:3] == (PARTIAL, session, 4), "coalesced audio failed")
    send(process, encode(FINISH, session, 4))
    check(read_frame_timeout(process)[:3] == (FINAL, session, 5), "finish failed")
    send(process, encode(SHUTDOWN, session, 5))
    finish_process(process, 0)


def test_authorization_and_identity_rejections(executable: Path) -> None:
    process = start_worker(executable)
    session, _ = bootstrap(process)
    send(process, encode(START_AUTH, session, 1, bytes(32)))
    expect_error(process, session, 2, b"start authorization rejected")

    process = start_worker(executable)
    session, digest = bootstrap(process)
    wrong_session = bytes((session[0] ^ 0xFF,)) + session[1:]
    send(process, encode(START_AUTH, wrong_session, 1, digest))
    expect_error(process, session, 2, b"session or sequence rejected")

    process = start_worker(executable)
    session, digest = bootstrap(process)
    authorize(process, session, digest)
    send(process, encode(START_SESSION, session, 1))
    expect_error(process, session, 3, b"session or sequence rejected")

    process = start_worker(executable)
    session, digest = bootstrap(process)
    authorize(process, session, digest)
    send(process, encode(START_AUTH, session, 2, digest))
    expect_error(process, session, 3, b"protocol state violation")


def rejected_raw_frame(executable: Path, make_frame: Callable[[bytes], bytes]) -> None:
    process = start_worker(executable)
    session, _ = bootstrap(process)
    send(process, make_frame(session))
    expect_error(process, session, 2, b"invalid protocol frame")


def test_malformed_and_bounded_frames(executable: Path) -> None:
    rejected_raw_frame(
        executable,
        lambda session: encode_header(START_AUTH, session, 1, 0, version=2),
    )
    rejected_raw_frame(
        executable,
        lambda session: encode_header(START_AUTH, session, 1, 0, flags=1),
    )
    rejected_raw_frame(
        executable,
        lambda session: encode_header(AUDIO, session, 1, MAX_AUDIO_BYTES + 2),
    )
    rejected_raw_frame(
        executable,
        lambda session: encode_header(AUDIO, session, 1, 0),
    )

    process = start_worker(executable)
    session, digest = bootstrap(process)
    authorize(process, session, digest)
    begin_session(process, session)
    send(process, encode(AUDIO, session, 3, bytes(MAX_AUDIO_BYTES)))
    check(read_frame_timeout(process)[:3] == (PARTIAL, session, 4), "max audio rejected")
    send(process, encode(SHUTDOWN, session, 4))
    finish_process(process, 0)


def test_state_and_transport_failures(executable: Path) -> None:
    process = start_worker(executable)
    session, digest = bootstrap(process)
    authorize(process, session, digest)
    send(process, encode(AUDIO, session, 2, b"\x00\x00"))
    expect_error(process, session, 3, b"audio rejected")

    process = start_worker(executable)
    bootstrap(process)
    assert process.stdin is not None
    process.stdin.close()
    finish_process(process, 4)

    process = start_worker(executable)
    session, digest = bootstrap(process)
    assert process.stdout is not None
    process.stdout.close()
    send(process, encode(START_AUTH, session, 1, digest))
    finish_process(process, 3)


def test_fault_hooks(executable: Path) -> None:
    process = start_worker(executable, "--test-exit-before-bootstrap")
    finish_process(process, 70)

    process = start_worker(executable, "--test-exit-after-bootstrap")
    bootstrap(process)
    finish_process(process, 71)

    process = start_worker(executable, "--test-fail-load")
    session, digest = bootstrap(process)
    send(process, encode(START_AUTH, session, 1, digest))
    expect_error(process, session, 2, b"backend load failed")

    process = start_worker(executable, "--test-exit-on-audio")
    session, digest = bootstrap(process)
    authorize(process, session, digest)
    begin_session(process, session)
    send(process, encode(AUDIO, session, 3, b"\x00\x00"))
    finish_process(process, 72)

    process = start_worker(executable, "--test-stall-on-audio")
    session, digest = bootstrap(process)
    authorize(process, session, digest)
    begin_session(process, session)
    send(process, encode(AUDIO, session, 3, b"\x00\x00"))
    try:
        process.wait(timeout=0.25)
    except subprocess.TimeoutExpired:
        check(True, "audio stall remained observable until supervisor termination")
    else:
        check(False, "stall hook exited before timeout")
    process.kill()
    process.wait(timeout=5)
    close_streams(process)
    check(not psutil.pid_exists(process.pid), "stalled worker survived forced cleanup")

    process = start_worker(executable, "--test-invalid-utf8-partial")
    session, digest = bootstrap(process)
    authorize(process, session, digest)
    begin_session(process, session)
    send(process, encode(AUDIO, session, 3, b"\x00\x00"))
    partial = read_frame_timeout(process)
    check(partial[:3] == (PARTIAL, session, 4), "fault result frame mismatch")
    try:
        partial[3].decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        check(True, "invalid UTF-8 fault remained invalid")
    else:
        check(False, "invalid UTF-8 hook produced valid text")
    send(process, encode(SHUTDOWN, session, 4))
    finish_process(process, 0)

    process = start_worker(executable, "--unknown-test-control")
    finish_process(process, 2)


def test_repeated_lifecycle_soak(executable: Path) -> None:
    parent = psutil.Process()
    handles_before = parent.num_handles()
    private_samples: list[int] = []
    for cycle in range(SOAK_CYCLES):
        process = start_worker(executable)
        session, digest = bootstrap(process)
        tracked = psutil.Process(process.pid)
        authorize(process, session, digest)
        begin_session(process, session)
        send(process, encode(AUDIO, session, 3, b"\x00\x00" * 8))
        check(read_frame_timeout(process)[:3] == (PARTIAL, session, 4), "soak partial failed")
        send(process, encode(FINISH, session, 4))
        check(read_frame_timeout(process)[:3] == (FINAL, session, 5), "soak final failed")
        memory = tracked.memory_info()
        private_samples.append(int(getattr(memory, "private", memory.rss)))
        send(process, encode(SHUTDOWN, session, 5))
        pid = process.pid
        finish_process(process, 0)
        check(not psutil.pid_exists(pid), f"soak cycle {cycle} left an orphan")

    check(max(private_samples) <= 64 * 1024 * 1024, "fake worker exceeded 64 MiB private")
    first_median = statistics.median(private_samples[:10])
    last_median = statistics.median(private_samples[-10:])
    check(last_median - first_median <= 16 * 1024 * 1024, "worker memory drifted")
    del process, tracked, memory
    gc.collect()
    time.sleep(0.05)
    handles_after = parent.num_handles()
    check(
        handles_after <= handles_before + 4,
        f"process test leaked parent handles: before={handles_before}, after={handles_after}",
    )


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: test-native-speech-worker.py WORKER_EXE", file=sys.stderr)
        return 2
    executable = Path(sys.argv[1]).resolve()
    check(executable.is_file(), f"worker executable not found: {executable}")
    test_full_lifecycle(executable)
    test_fragmented_and_coalesced_input(executable)
    test_authorization_and_identity_rejections(executable)
    test_malformed_and_bounded_frames(executable)
    test_state_and_transport_failures(executable)
    test_fault_hooks(executable)
    test_repeated_lifecycle_soak(executable)
    print(
        f"Speech worker process contract passed: {checks} checks ({SOAK_CYCLES} lifecycle cycles)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
