"""Governed binary-protocol adapter for the native speech worker."""

from __future__ import annotations

import hashlib
import os
import queue
import struct
import subprocess
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import IntEnum, StrEnum
from pathlib import Path
from typing import IO

import psutil  # type: ignore[import-untyped]

from jarvis.runtime.broker import WindowsJobObject
from jarvis.runtime.memory import MemoryAdmissionError, MemoryGovernor
from jarvis.runtime.worker import GovernedWorkerSlot, JobFactory

_MAGIC = 0x5454534A
_VERSION = 1
_HEADER_BYTES = 40
_MAX_PAYLOAD_BYTES = 65_536
_MAX_AUDIO_BYTES = 32_768
_MAX_TEXT_BYTES = 8_192
_AUTH_LABEL = b"jarvis-stt-start-auth-v1"
_REQUIRED_CAPABILITIES = 0x3
_HEADER = struct.Struct("<IHHHHI16sQ")


class NativeSpeechMessage(IntEnum):
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


class NativeSpeechState(StrEnum):
    NEW = "new"
    LEASED = "leased"
    SPAWNED_UNAUTHORIZED = "spawned_unauthorized"
    CONTAINED = "contained"
    READY = "ready"
    LISTENING = "listening"
    FINISHED = "finished"
    CANCELLED = "cancelled"
    FAILED = "failed"
    CLOSED = "closed"


class NativeSpeechWorkerError(RuntimeError):
    def __init__(self, code: str, detail: str | None = None) -> None:
        self.code = code
        self.detail = detail
        super().__init__(code if detail is None else f"{code}: {detail}")


@dataclass(frozen=True, slots=True)
class NativeSpeechWorkerConfig:
    executable: Path
    startup_timeout_seconds: float = 5.0
    response_timeout_seconds: float = 5.0
    shutdown_timeout_seconds: float = 2.0
    response_queue_limit: int = 8

    def validate(self) -> None:
        if not self.executable.is_file():
            raise FileNotFoundError(f"native speech worker not found: {self.executable}")
        if not 0 < self.startup_timeout_seconds <= 60:
            raise ValueError("startup timeout must be between 0 and 60 seconds")
        if not 0 < self.response_timeout_seconds <= 60:
            raise ValueError("response timeout must be between 0 and 60 seconds")
        if not 0 < self.shutdown_timeout_seconds <= 30:
            raise ValueError("shutdown timeout must be between 0 and 30 seconds")
        if not 1 <= self.response_queue_limit <= 64:
            raise ValueError("response queue limit must be between 1 and 64")


@dataclass(frozen=True, slots=True)
class NativeSpeechStartup:
    process_id: int
    session_id: bytes
    capabilities: int


@dataclass(frozen=True, slots=True)
class NativeSpeechMetrics:
    startup_latency_ms: float
    request_count: int
    maximum_response_latency_ms: float
    peak_private_bytes: int
    peak_working_set_bytes: int
    peak_job_process_bytes: int
    peak_job_bytes: int
    exit_reason: str | None


@dataclass(frozen=True, slots=True)
class _Frame:
    message_type: NativeSpeechMessage
    session_id: bytes
    sequence: int
    payload: bytes


ProcessFactory = Callable[[list[str]], subprocess.Popen[bytes]]


def _default_process_factory(command: list[str]) -> subprocess.Popen[bytes]:
    creation_flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    return subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        bufsize=0,
        shell=False,
        creationflags=creation_flags,
    )


def _read_exact(stream: IO[bytes], size: int) -> bytes:
    chunks = bytearray()
    while len(chunks) < size:
        chunk = stream.read(size - len(chunks))
        if not chunk:
            raise NativeSpeechWorkerError("worker_stream_closed")
        chunks.extend(chunk)
    return bytes(chunks)


def _decode_text(payload: bytes) -> str:
    if b"\x00" in payload:
        raise NativeSpeechWorkerError("worker_text_invalid")
    try:
        return payload.decode("utf-8", errors="strict")
    except UnicodeDecodeError as error:
        raise NativeSpeechWorkerError("worker_text_invalid") from error


def _read_frame(stream: IO[bytes]) -> _Frame:
    raw = _read_exact(stream, _HEADER_BYTES)
    magic, version, header_size, raw_type, flags, size, session, sequence = _HEADER.unpack(raw)
    if magic != _MAGIC or version != _VERSION or header_size != _HEADER_BYTES:
        raise NativeSpeechWorkerError("worker_header_invalid")
    if flags != 0 or not any(session) or sequence == 0:
        raise NativeSpeechWorkerError("worker_header_invalid")
    try:
        message_type = NativeSpeechMessage(raw_type)
    except ValueError as error:
        raise NativeSpeechWorkerError("worker_message_type_invalid") from error
    if size > _MAX_PAYLOAD_BYTES:
        raise NativeSpeechWorkerError("worker_payload_limit")
    if message_type is NativeSpeechMessage.BOOTSTRAP and size != 40:
        raise NativeSpeechWorkerError("worker_payload_invalid")
    if (
        message_type
        in {
            NativeSpeechMessage.READY,
            NativeSpeechMessage.CANCEL,
        }
        and size != 0
    ):
        raise NativeSpeechWorkerError("worker_payload_invalid")
    if message_type in {NativeSpeechMessage.PARTIAL, NativeSpeechMessage.FINAL} and (
        size > _MAX_TEXT_BYTES
    ):
        raise NativeSpeechWorkerError("worker_payload_limit")
    if message_type is NativeSpeechMessage.ERROR and size > 4096:
        raise NativeSpeechWorkerError("worker_payload_limit")
    payload = _read_exact(stream, size)
    if message_type in {
        NativeSpeechMessage.PARTIAL,
        NativeSpeechMessage.FINAL,
        NativeSpeechMessage.ERROR,
    }:
        _decode_text(payload)
    return _Frame(message_type, session, sequence, payload)


class NativeSpeechWorkerAdapter:
    """Owns one contained native worker and its binary protocol lifecycle."""

    def __init__(
        self,
        config: NativeSpeechWorkerConfig,
        governor: MemoryGovernor,
        *,
        profile_name: str = "native-stt-candidate",
        certification_mode: bool = False,
        job_factory: JobFactory = WindowsJobObject,
        process_factory: ProcessFactory = _default_process_factory,
    ) -> None:
        self.config = config
        self._slot = GovernedWorkerSlot(
            governor,
            profile_name,
            certification_mode=certification_mode,
            job_factory=job_factory,
        )
        self._process_factory = process_factory
        self._process: subprocess.Popen[bytes] | None = None
        self._responses: queue.Queue[_Frame | NativeSpeechWorkerError] = queue.Queue(
            maxsize=config.response_queue_limit
        )
        self._reader_thread: threading.Thread | None = None
        self._reader_failure: NativeSpeechWorkerError | None = None
        self._write_lock = threading.Lock()
        self._session_id: bytes | None = None
        self._outbound_sequence = 0
        self._inbound_sequence = 0
        self._startup_latency_ms = 0.0
        self._request_count = 0
        self._maximum_response_latency_ms = 0.0
        self._peak_private_bytes = 0
        self._peak_working_set_bytes = 0
        self._peak_job_process_bytes = 0
        self._peak_job_bytes = 0
        self._exit_reason: str | None = None
        self.state = NativeSpeechState.NEW

    @property
    def process_id(self) -> int | None:
        return self._process.pid if self._process is not None else None

    @property
    def containment_verified(self) -> bool:
        return self._slot.containment_verified

    @property
    def metrics(self) -> NativeSpeechMetrics:
        return NativeSpeechMetrics(
            startup_latency_ms=self._startup_latency_ms,
            request_count=self._request_count,
            maximum_response_latency_ms=self._maximum_response_latency_ms,
            peak_private_bytes=self._peak_private_bytes,
            peak_working_set_bytes=self._peak_working_set_bytes,
            peak_job_process_bytes=self._peak_job_process_bytes,
            peak_job_bytes=self._peak_job_bytes,
            exit_reason=self._exit_reason,
        )

    def _reader(self) -> None:
        process = self._process
        if process is None or process.stdout is None:
            return
        try:
            while True:
                frame = _read_frame(process.stdout)
                try:
                    self._responses.put_nowait(frame)
                except queue.Full:
                    raise NativeSpeechWorkerError("worker_response_queue_full") from None
        except NativeSpeechWorkerError as error:
            self._reader_failure = error
            try:
                self._responses.put_nowait(error)
            except queue.Full:
                pass

    def _deadline(self, timeout: float) -> float:
        return time.monotonic() + timeout

    def _receive(self, expected: NativeSpeechMessage, deadline: float) -> _Frame:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise NativeSpeechWorkerError("worker_response_timeout")
        try:
            item = self._responses.get(timeout=remaining)
        except queue.Empty as error:
            if self._reader_failure is not None:
                raise self._reader_failure from None
            raise NativeSpeechWorkerError("worker_response_timeout") from error
        if isinstance(item, NativeSpeechWorkerError):
            raise item
        if self._session_id is not None and item.session_id != self._session_id:
            raise NativeSpeechWorkerError("worker_session_mismatch")
        next_sequence = self._inbound_sequence + 1
        if item.sequence != next_sequence:
            raise NativeSpeechWorkerError("worker_sequence_mismatch")
        self._inbound_sequence = item.sequence
        if item.message_type is NativeSpeechMessage.ERROR:
            raise NativeSpeechWorkerError("worker_rejected_request", _decode_text(item.payload))
        if item.message_type is not expected:
            raise NativeSpeechWorkerError("worker_response_unexpected")
        return item

    def _send(self, message_type: NativeSpeechMessage, payload: bytes = b"") -> None:
        process = self._process
        session = self._session_id
        if process is None or process.stdin is None or session is None:
            raise NativeSpeechWorkerError("worker_not_connected")
        if len(payload) > _MAX_PAYLOAD_BYTES:
            raise NativeSpeechWorkerError("request_payload_limit")
        sequence = self._outbound_sequence + 1
        encoded = _HEADER.pack(
            _MAGIC,
            _VERSION,
            _HEADER_BYTES,
            int(message_type),
            0,
            len(payload),
            session,
            sequence,
        )
        try:
            with self._write_lock:
                process.stdin.write(encoded)
                if payload:
                    process.stdin.write(payload)
                process.stdin.flush()
        except (BrokenPipeError, OSError, ValueError) as error:
            raise NativeSpeechWorkerError("worker_write_failed") from error
        self._outbound_sequence = sequence

    def _observe_memory(self) -> None:
        process = self._process
        if process is None:
            return
        try:
            memory = psutil.Process(process.pid).memory_info()
            observed = int(getattr(memory, "private", memory.rss))
            self._peak_private_bytes = max(self._peak_private_bytes, observed)
            self._peak_working_set_bytes = max(
                self._peak_working_set_bytes,
                int(memory.rss),
            )
            self._slot.update_observed_private_bytes(observed)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return

    def start(self) -> NativeSpeechStartup:
        if self.state is not NativeSpeechState.NEW:
            raise NativeSpeechWorkerError("worker_already_started")
        self.config.validate()
        started_at = time.monotonic()
        try:
            self._slot.start()
            self.state = NativeSpeechState.LEASED
            self._process = self._process_factory([str(self.config.executable.resolve())])
            if self._process.stdin is None or self._process.stdout is None:
                raise NativeSpeechWorkerError("worker_pipes_missing")
            self.state = NativeSpeechState.SPAWNED_UNAUTHORIZED
            self._reader_thread = threading.Thread(
                target=self._reader,
                name="jarvis-native-speech-reader",
                daemon=True,
            )
            self._reader_thread.start()
            deadline = self._deadline(self.config.startup_timeout_seconds)
            bootstrap = self._receive(NativeSpeechMessage.BOOTSTRAP, deadline)
            if bootstrap.sequence != 1:
                raise NativeSpeechWorkerError("worker_sequence_mismatch")
            process_id, capabilities = struct.unpack_from("<II", bootstrap.payload)
            if self._process.pid != process_id:
                raise NativeSpeechWorkerError("worker_pid_mismatch")
            if capabilities & _REQUIRED_CAPABILITIES != _REQUIRED_CAPABILITIES:
                raise NativeSpeechWorkerError("worker_capability_missing")
            self._session_id = bootstrap.session_id
            self._slot.assign_pid(process_id)
            try:
                self._slot.verify_pid(process_id)
            except RuntimeError as error:
                raise NativeSpeechWorkerError("worker_containment_unverified") from error
            if not self._slot.containment_verified:
                raise NativeSpeechWorkerError("worker_containment_unverified")
            self.state = NativeSpeechState.CONTAINED
            nonce = bootstrap.payload[8:]
            digest = hashlib.sha256(_AUTH_LABEL + self._session_id + nonce).digest()
            self._send(NativeSpeechMessage.START_AUTH, digest)
            self._receive(NativeSpeechMessage.READY, deadline)
            self._observe_memory()
            self._capture_job_peaks()
            self._startup_latency_ms = (time.monotonic() - started_at) * 1000.0
            self.state = NativeSpeechState.READY
            return NativeSpeechStartup(process_id, self._session_id, capabilities)
        except Exception as error:
            self._exit_reason = (
                error.code if isinstance(error, NativeSpeechWorkerError) else type(error).__name__
            )
            self.state = NativeSpeechState.FAILED
            self._cleanup()
            if isinstance(
                error,
                (
                    NativeSpeechWorkerError,
                    MemoryAdmissionError,
                    FileNotFoundError,
                    ValueError,
                ),
            ):
                raise
            raise NativeSpeechWorkerError("worker_start_failed") from error

    def _require_state(self, *states: NativeSpeechState) -> None:
        if self.state not in states:
            raise NativeSpeechWorkerError("worker_state_invalid")

    def start_session(self) -> None:
        self._require_state(NativeSpeechState.READY)
        self._request(NativeSpeechMessage.START_SESSION, NativeSpeechMessage.READY)
        self.state = NativeSpeechState.LISTENING

    def accept_audio(self, pcm16: bytes) -> str:
        self._require_state(NativeSpeechState.LISTENING)
        if not pcm16 or len(pcm16) > _MAX_AUDIO_BYTES or len(pcm16) % 2 != 0:
            raise ValueError("audio must be non-empty even-length PCM16 within 32768 bytes")
        frame = self._request(
            NativeSpeechMessage.AUDIO,
            NativeSpeechMessage.PARTIAL,
            pcm16,
        )
        return _decode_text(frame.payload)

    def finish(self) -> str:
        self._require_state(NativeSpeechState.LISTENING)
        frame = self._request(NativeSpeechMessage.FINISH, NativeSpeechMessage.FINAL)
        self.state = NativeSpeechState.FINISHED
        return _decode_text(frame.payload)

    def cancel(self) -> None:
        self._require_state(NativeSpeechState.READY, NativeSpeechState.LISTENING)
        self._request(NativeSpeechMessage.CANCEL, NativeSpeechMessage.CANCEL)
        self.state = NativeSpeechState.CANCELLED

    def reset(self) -> None:
        self._require_state(NativeSpeechState.FINISHED, NativeSpeechState.CANCELLED)
        self._request(NativeSpeechMessage.RESET, NativeSpeechMessage.READY)
        self.state = NativeSpeechState.READY

    def _request(
        self,
        request: NativeSpeechMessage,
        response: NativeSpeechMessage,
        payload: bytes = b"",
    ) -> _Frame:
        started_at = time.monotonic()
        try:
            self._send(request, payload)
            frame = self._receive(
                response,
                self._deadline(self.config.response_timeout_seconds),
            )
            self._observe_memory()
            self._capture_job_peaks()
            elapsed_ms = (time.monotonic() - started_at) * 1000.0
            self._request_count += 1
            self._maximum_response_latency_ms = max(
                self._maximum_response_latency_ms,
                elapsed_ms,
            )
            return frame
        except Exception as error:
            self._exit_reason = (
                error.code if isinstance(error, NativeSpeechWorkerError) else type(error).__name__
            )
            self.state = NativeSpeechState.FAILED
            self._cleanup()
            raise

    def _capture_job_peaks(self) -> None:
        try:
            process_peak, job_peak = self._slot.memory_peaks()
        except RuntimeError:
            return
        self._peak_job_process_bytes = max(
            self._peak_job_process_bytes,
            process_peak,
        )
        self._peak_job_bytes = max(self._peak_job_bytes, job_peak)

    def _cleanup(self) -> None:
        process = self._process
        self._observe_memory()
        self._capture_job_peaks()
        slot_error: Exception | None = None
        try:
            self._slot.close()
        except Exception as error:
            slot_error = error
        try:
            if process is not None and process.poll() is None:
                process.kill()
            if process is not None:
                try:
                    process.wait(timeout=self.config.shutdown_timeout_seconds)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=self.config.shutdown_timeout_seconds)
                for stream in (process.stdin, process.stdout):
                    if stream is not None and not stream.closed:
                        stream.close()
            reader = self._reader_thread
            if reader is not None and reader is not threading.current_thread():
                reader.join(timeout=self.config.shutdown_timeout_seconds)
        finally:
            if slot_error is not None:
                raise slot_error

    def close(self) -> None:
        if self.state is NativeSpeechState.CLOSED:
            return
        process = self._process
        if (
            process is not None
            and process.poll() is None
            and self._session_id is not None
            and self.state is not NativeSpeechState.FAILED
        ):
            try:
                self._send(NativeSpeechMessage.SHUTDOWN)
                process.wait(timeout=self.config.shutdown_timeout_seconds)
                self._exit_reason = "clean_shutdown"
            except (NativeSpeechWorkerError, subprocess.TimeoutExpired):
                self._exit_reason = "forced_shutdown"
                pass
        self._cleanup()
        self.state = NativeSpeechState.CLOSED

    def __enter__(self) -> NativeSpeechWorkerAdapter:
        self.start()
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()


__all__ = [
    "NativeSpeechMessage",
    "NativeSpeechMetrics",
    "NativeSpeechStartup",
    "NativeSpeechState",
    "NativeSpeechWorkerAdapter",
    "NativeSpeechWorkerConfig",
    "NativeSpeechWorkerError",
]
