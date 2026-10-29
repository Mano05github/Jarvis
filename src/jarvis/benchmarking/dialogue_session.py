"""Hash-bound dialogue recording sessions and evaluation-manifest consolidation."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Literal, cast

from pydantic import BaseModel, ConfigDict, Field, field_validator

from jarvis.benchmarking.corpus import CorpusEntry
from jarvis.benchmarking.dialogue import (
    DialogueScenario,
    DialogueSpeechEntry,
    Scalar,
)
from jarvis.benchmarking.recording import validate_recording

CriticalMarker = Literal["affirmation", "cancellation", "correction", "negation"]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class SessionRecording(BaseModel):
    """One legacy or v2 recording observation from a recording session."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    utterance_id: str | None = None
    recording_id: str | None = None
    recorded_at_utc: str | None = None
    path: str = Field(min_length=1)
    audio_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    archived_previous: str | None = None
    duration_seconds: float = Field(gt=0)
    sample_rate_hz: int
    channels: int
    sample_width_bytes: int
    frames: int = Field(gt=0)
    rms_dbfs: float
    active_rms_dbfs: float
    peak_dbfs: float
    scenario_id: str | None = None
    turn_id: str | None = None
    spoken_reference: str | None = None

    @field_validator("path", "archived_previous")
    @classmethod
    def validate_relative_path(cls, value: str | None) -> str | None:
        if value is None:
            return value
        path = Path(value)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("recording paths must remain relative to the corpus root")
        return value


class RecordingSession(BaseModel):
    """A complete recording-session document; v1 remains readable for migration."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0", "2.0"]
    session_id: str | None = None
    created_at_utc: str | None = None
    source_manifest_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    selected: int = Field(ge=0)
    recorded: int = Field(ge=0)
    skipped: int = Field(ge=0)
    stopped_early: bool
    recordings: tuple[SessionRecording, ...]


class DialogueEvaluationEntry(BaseModel):
    """Immutable link between current audio, actual speech and semantic expectation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"] = "1.0"
    utterance_id: str = Field(pattern=r"^tg_[0-9]{3}$")
    scenario_id: str = Field(pattern=r"^dlg_[0-9]{3}$")
    turn_id: str = Field(pattern=r"^dlg_[0-9]{3}_t[0-9]{2}$")
    condition: Literal["quiet-near", "normal-room", "controlled-noise"]
    split: Literal["development", "held-out"]
    audio_file: str
    audio_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    spoken_reference: str = Field(min_length=1)
    expected_dialogue_act: Literal["command", "query", "correction", "cancel", "confirm"]
    expected_intent: str = Field(min_length=1)
    expected_slots: dict[str, Scalar] = Field(default_factory=dict)
    expected_referents: tuple[str, ...] = ()
    expected_policy: Literal["none", "allow", "confirm", "deny"]
    requires_context: bool
    critical_markers: tuple[CriticalMarker, ...] = ()
    source_session: str = Field(min_length=1)

    @field_validator("audio_file")
    @classmethod
    def validate_audio_file(cls, value: str) -> str:
        path = Path(value)
        if path.is_absolute() or ".." in path.parts or path.suffix.lower() != ".wav":
            raise ValueError("audio_file must be a relative WAV path")
        return value


def load_recording_session(path: Path) -> RecordingSession:
    return RecordingSession.model_validate_json(path.read_text(encoding="utf-8"))


def load_evaluation_manifest(path: Path) -> list[DialogueEvaluationEntry]:
    entries: list[DialogueEvaluationEntry] = []
    identifiers: set[str] = set()
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        entry = DialogueEvaluationEntry.model_validate_json(line)
        if entry.utterance_id in identifiers:
            raise ValueError(
                f"duplicate evaluation utterance on line {line_number}: {entry.utterance_id}"
            )
        identifiers.add(entry.utterance_id)
        entries.append(entry)
    if not entries:
        raise ValueError("evaluation manifest is empty")
    return entries


def write_evaluation_manifest(entries: list[DialogueEvaluationEntry], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(entry.model_dump_json() for entry in entries) + "\n",
        encoding="utf-8",
    )


def _marker_for(act: str, text: str) -> tuple[CriticalMarker, ...]:
    markers: list[CriticalMarker] = []
    lowered = text.casefold()
    if act == "confirm":
        markers.append("affirmation")
    if act == "cancel":
        markers.append("cancellation")
    if act == "correction":
        markers.append("correction")
    if any(token in lowered.split() for token in ("illa", "vendam", "venam", "no")):
        markers.append("negation")
    return tuple(markers)


def _recording_utterance_id(recording: SessionRecording) -> str:
    return recording.utterance_id or Path(recording.path).stem


def _matches_current_audio(recording: SessionRecording, audio: Path, audio_hash: str) -> bool:
    if recording.audio_sha256 is not None:
        return recording.audio_sha256 == audio_hash
    stats = validate_recording(audio)
    duration_matches = abs(recording.duration_seconds - stats.duration_seconds) < 0.001
    return recording.frames == stats.frames and duration_matches


def consolidate_dialogue_sessions(
    prompts: list[DialogueSpeechEntry],
    scenarios: list[DialogueScenario],
    session_paths: list[Path],
    corpus_root: Path,
) -> tuple[list[DialogueEvaluationEntry], list[CorpusEntry], dict[str, object]]:
    """Select the unique session observation matching each current canonical WAV."""
    root = corpus_root.resolve()
    turns = {
        turn.turn_id: turn
        for scenario in scenarios
        for turn in scenario.turns
        if turn.speaker == "owner"
    }
    observations: dict[str, list[tuple[Path, SessionRecording]]] = {}
    for session_path in sorted(session_paths):
        session = load_recording_session(session_path)
        for recording in session.recordings:
            utterance_id = _recording_utterance_id(recording)
            observations.setdefault(utterance_id, []).append((session_path, recording))

    evaluation: list[DialogueEvaluationEntry] = []
    acoustic: list[CorpusEntry] = []
    missing: list[str] = []
    stale_observations = 0
    for prompt in prompts:
        audio = (root / prompt.audio_file).resolve()
        if not audio.is_relative_to(root):
            raise ValueError(f"audio path escapes corpus root: {prompt.audio_file}")
        candidates = observations.get(prompt.utterance_id, [])
        if not audio.is_file() or not candidates:
            missing.append(prompt.utterance_id)
            continue
        audio_hash = sha256_file(audio)
        matching = [
            item for item in candidates if _matches_current_audio(item[1], audio, audio_hash)
        ]
        stale_observations += len(candidates) - len(matching)
        if not matching:
            raise ValueError(
                f"no session observation matches current audio for {prompt.utterance_id}"
            )
        references = {item[1].spoken_reference for item in matching}
        if len(matching) > 1 and len(references) > 1:
            raise ValueError(f"conflicting matching session observations for {prompt.utterance_id}")
        session_path, recording = matching[-1]
        if recording.scenario_id not in {None, prompt.scenario_id}:
            raise ValueError(f"scenario mismatch for {prompt.utterance_id}")
        if recording.turn_id not in {None, prompt.turn_id}:
            raise ValueError(f"turn mismatch for {prompt.utterance_id}")
        spoken_reference = recording.spoken_reference
        if not spoken_reference:
            raise ValueError(f"missing spoken reference for {prompt.utterance_id}")
        turn = turns.get(prompt.turn_id)
        if turn is None or turn.intent_label != prompt.intent_label:
            raise ValueError(f"dialogue expectation mismatch for {prompt.utterance_id}")
        owner_act = cast(
            Literal["command", "query", "correction", "cancel", "confirm"],
            turn.dialogue_act,
        )
        try:
            source_session = str(session_path.resolve().relative_to(root))
        except ValueError:
            source_session = str(session_path.resolve())
        entry = DialogueEvaluationEntry(
            utterance_id=prompt.utterance_id,
            scenario_id=prompt.scenario_id,
            turn_id=prompt.turn_id,
            condition=prompt.condition,
            split=prompt.split,
            audio_file=prompt.audio_file,
            audio_sha256=audio_hash,
            spoken_reference=spoken_reference,
            expected_dialogue_act=owner_act,
            expected_intent=turn.intent_label,
            expected_slots=turn.slots,
            expected_referents=turn.refers_to,
            expected_policy=turn.expected_policy,
            requires_context=turn.requires_context,
            critical_markers=_marker_for(turn.dialogue_act, spoken_reference),
            source_session=source_session,
        )
        evaluation.append(entry)
        acoustic.append(
            CorpusEntry(
                utterance_id=prompt.utterance_id,
                language="mixed",
                reference=spoken_reference,
                intent_label=prompt.intent_label,
                condition=prompt.condition,
                split=prompt.split,
                audio_file=prompt.audio_file,
                consented=True,
                retain_until=prompt.retain_until,
            )
        )
    summary: dict[str, object] = {
        "schema_version": "1.0",
        "prompts": len(prompts),
        "consolidated": len(evaluation),
        "missing": missing,
        "stale_observations_ignored": stale_observations,
        "sessions": len(session_paths),
    }
    return evaluation, acoustic, summary


def write_summary(summary: dict[str, object], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
