"""Native Windows recording workflow for the consented benchmark corpus."""

from __future__ import annotations

import array
import ctypes
import hashlib
import math
import os
import statistics
import sys
import wave
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol
from uuid import uuid4

from jarvis.benchmarking.corpus import CorpusEntry
from jarvis.benchmarking.dialogue import DialogueSpeechEntry


@dataclass(frozen=True)
class RecordingStats:
    path: str
    duration_seconds: float
    sample_rate_hz: int
    channels: int
    sample_width_bytes: int
    frames: int
    rms_dbfs: float
    active_rms_dbfs: float
    peak_dbfs: float


class Recorder(Protocol):
    def start(self) -> None: ...

    def stop_and_save(self, output: Path) -> None: ...

    def cancel(self) -> None: ...


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _archive_existing(target: Path, root: Path, utterance_id: str) -> Path:
    old_hash = _sha256_file(target)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    archive = root / "revisions" / utterance_id / f"{timestamp}-{old_hash[:16]}.wav"
    archive.parent.mkdir(parents=True, exist_ok=True)
    target.replace(archive)
    return archive


def validate_recording(path: Path) -> RecordingStats:
    """Require the canonical 16 kHz, mono, 16-bit PCM corpus format."""
    with wave.open(str(path), "rb") as audio:
        channels = audio.getnchannels()
        sample_width = audio.getsampwidth()
        sample_rate = audio.getframerate()
        frames = audio.getnframes()
        compression = audio.getcomptype()
        samples = array.array("h", audio.readframes(frames))
    if compression != "NONE":
        raise ValueError(f"recording must use PCM encoding, got {compression}")
    if channels != 1 or sample_width != 2 or sample_rate != 16_000:
        raise ValueError(
            "recording must be mono 16-bit PCM at 16000 Hz; "
            f"got channels={channels}, width={sample_width}, rate={sample_rate}"
        )
    if frames < 1_600:
        raise ValueError("recording must contain at least 0.1 seconds of audio")
    if sys.byteorder != "little":
        samples.byteswap()
    rms = math.sqrt(sum(sample * sample for sample in samples) / max(1, len(samples)))
    peak = max((abs(sample) for sample in samples), default=0)
    frame_size = max(1, sample_rate // 50)
    frame_levels: list[float] = []
    for start in range(0, len(samples), frame_size):
        frame = samples[start : start + frame_size]
        frame_rms = math.sqrt(sum(sample * sample for sample in frame) / max(1, len(frame)))
        frame_levels.append(20 * math.log10(max(1.0, frame_rms) / 32_768))
    ordered_levels = sorted(frame_levels)
    noise_floor = ordered_levels[max(0, round((len(ordered_levels) - 1) * 0.2))]
    active_threshold = max(-45.0, noise_floor + 10.0)
    active_levels = [level for level in frame_levels if level >= active_threshold]
    active_rms_dbfs = statistics.median(active_levels) if active_levels else -90.3
    return RecordingStats(
        path=str(path),
        duration_seconds=frames / sample_rate,
        sample_rate_hz=sample_rate,
        channels=channels,
        sample_width_bytes=sample_width,
        frames=frames,
        rms_dbfs=20 * math.log10(max(1.0, rms) / 32_768),
        active_rms_dbfs=active_rms_dbfs,
        peak_dbfs=20 * math.log10(max(1, peak) / 32_768),
    )


class MciWaveRecorder:
    """Record from the Windows default input through the built-in MCI API."""

    def __init__(self) -> None:
        if os.name != "nt":
            raise OSError("MCI recording is available only on Windows")
        loader = ctypes.WinDLL
        self._winmm: Any = loader("winmm")
        self._send: Any = self._winmm.mciSendStringW
        self._error_text: Any = self._winmm.mciGetErrorStringW
        self._alias: str | None = None

    def _command(self, command: str) -> str:
        response = ctypes.create_unicode_buffer(512)
        code = int(self._send(command, response, len(response), None))
        if code:
            message = ctypes.create_unicode_buffer(512)
            self._error_text(code, message, len(message))
            raise OSError(f"Windows audio command failed ({code}): {message.value}")
        return response.value

    def start(self) -> None:
        if self._alias is not None:
            raise RuntimeError("recording is already active")
        alias = f"jarvis_{uuid4().hex}"
        self._command(f"open new type waveaudio alias {alias}")
        self._alias = alias
        try:
            self._command(
                f"set {alias} time format milliseconds channels 1 "
                "samplespersec 16000 bitspersample 16 alignment 2 bytespersec 32000"
            )
            self._command(f"record {alias}")
        except Exception:
            self.cancel()
            raise

    def stop_and_save(self, output: Path) -> None:
        if self._alias is None:
            raise RuntimeError("recording is not active")
        alias = self._alias
        output.parent.mkdir(parents=True, exist_ok=True)
        if '"' in str(output):
            raise ValueError("recording path cannot contain a quote")
        try:
            self._command(f"stop {alias}")
            self._command(f'save {alias} "{output}"')
        finally:
            self._command(f"close {alias}")
            self._alias = None

    def cancel(self) -> None:
        if self._alias is not None:
            alias = self._alias
            self._alias = None
            self._command(f"close {alias}")


def record_corpus_interactive(
    entries: Sequence[CorpusEntry | DialogueSpeechEntry],
    corpus_root: Path,
    recorder: Recorder,
    *,
    input_fn: Callable[[str], str] = input,
    output_fn: Callable[[str], None] = print,
    overwrite: bool = False,
    start_at: str | None = None,
    limit: int | None = None,
) -> dict[str, object]:
    """Guide the owner through explicit, one-file-at-a-time corpus recording."""
    root = corpus_root.resolve()
    dialogue_session = any(isinstance(entry, DialogueSpeechEntry) for entry in entries)
    session_id = uuid4().hex if dialogue_session else None
    session_created = datetime.now(UTC).isoformat() if dialogue_session else None
    selected = list(entries)
    if start_at is not None:
        identifiers = [entry.utterance_id for entry in selected]
        if start_at not in identifiers:
            raise ValueError(f"start utterance not found: {start_at}")
        selected = selected[identifiers.index(start_at) :]
    if limit is not None:
        if limit < 1:
            raise ValueError("recording limit must be positive")
        selected = selected[:limit]

    recorded: list[dict[str, object]] = []
    skipped = 0
    stopped = False
    try:
        for position, entry in enumerate(selected, 1):
            target = (root / entry.audio_file).resolve()
            if not target.is_relative_to(root):
                raise ValueError(f"audio path escapes corpus root: {entry.audio_file}")
            if target.suffix.lower() != ".wav":
                raise ValueError("native corpus recorder supports WAV targets only")
            if target.exists() and not overwrite:
                skipped += 1
                continue

            output_fn(
                f"[{position}/{len(selected)}] {entry.utterance_id} | "
                f"{entry.language} | {entry.condition} | {entry.split}"
            )
            if isinstance(entry, DialogueSpeechEntry):
                output_fn(f"Situation: {entry.elicitation}")
                output_fn(f"Natural example: {entry.reference}")
                output_fn("Say it naturally in your own Tanglish; do not read it mechanically.")
            else:
                output_fn(f"Say: {entry.reference}")
            action = input_fn("Enter=record, s=skip, q=quit: ").strip().lower()
            if action == "q":
                stopped = True
                break
            if action == "s":
                skipped += 1
                continue
            if action:
                output_fn("Unknown choice; utterance skipped.")
                skipped += 1
                continue

            partial = target.with_name(f"{target.stem}.partial.wav")
            partial.unlink(missing_ok=True)
            recorder.start()
            finish = input_fn("Recording... Enter=stop, c=cancel: ").strip().lower()
            if finish == "c":
                recorder.cancel()
                skipped += 1
                continue
            recorder.stop_and_save(partial)
            try:
                stats = validate_recording(partial)
            except Exception:
                partial.unlink(missing_ok=True)
                raise
            output_fn(
                f"Level: speech-active RMS {stats.active_rms_dbfs:.1f} dBFS, "
                f"overall RMS {stats.rms_dbfs:.1f} dBFS, peak {stats.peak_dbfs:.1f} dBFS"
            )
            if stats.active_rms_dbfs < -36 and stats.peak_dbfs < -20:
                output_fn("Warning: speech level is low; move closer or increase input gain.")
            spoken_reference: str | None = None
            if isinstance(entry, DialogueSpeechEntry):
                typed_reference = input_fn(
                    "Type what you actually said (Enter=natural example): "
                ).strip()
                spoken_reference = typed_reference or entry.reference

            archived_previous: Path | None = None
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                archived_previous = _archive_existing(target, root, entry.utterance_id)
            try:
                partial.replace(target)
            except Exception:
                if archived_previous is not None and not target.exists():
                    archived_previous.replace(target)
                raise
            recording: dict[str, object] = {
                **asdict(stats),
                "path": str(target.relative_to(root)),
            }
            if isinstance(entry, DialogueSpeechEntry):
                recording.update(
                    {
                        "utterance_id": entry.utterance_id,
                        "recording_id": uuid4().hex,
                        "recorded_at_utc": datetime.now(UTC).isoformat(),
                        "audio_sha256": _sha256_file(target),
                        "archived_previous": (
                            str(archived_previous.relative_to(root))
                            if archived_previous is not None
                            else None
                        ),
                        "scenario_id": entry.scenario_id,
                        "turn_id": entry.turn_id,
                        "spoken_reference": spoken_reference,
                    }
                )
            recorded.append(recording)
    finally:
        recorder.cancel()

    session_metadata: dict[str, object] = (
        {"session_id": session_id, "created_at_utc": session_created} if dialogue_session else {}
    )
    return {
        "schema_version": "2.0" if dialogue_session else "1.0",
        **session_metadata,
        "selected": len(selected),
        "recorded": len(recorded),
        "skipped": skipped,
        "stopped_early": stopped,
        "recordings": recorded,
    }
