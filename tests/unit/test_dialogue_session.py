import json
import wave
from pathlib import Path

import pytest

from jarvis.benchmarking.dialogue_pack import (
    build_phase1_dialogue_speech,
    build_phase1_dialogues,
)
from jarvis.benchmarking.dialogue_session import (
    RecordingSession,
    SessionRecording,
    consolidate_dialogue_sessions,
    load_evaluation_manifest,
    sha256_file,
    write_evaluation_manifest,
)


def write_wav(path: Path, frames: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(16_000)
        audio.writeframes(b"\x10\x00" * frames)


def observation(frames: int, reference: str) -> SessionRecording:
    return SessionRecording(
        path="raw/mixed-v2/tg_004.wav",
        duration_seconds=frames / 16_000,
        sample_rate_hz=16_000,
        channels=1,
        sample_width_bytes=2,
        frames=frames,
        rms_dbfs=-35.0,
        active_rms_dbfs=-32.0,
        peak_dbfs=-18.0,
        scenario_id="dlg_001",
        turn_id="dlg_001_t07",
        spoken_reference=reference,
    )


def write_session(path: Path, item: SessionRecording) -> None:
    session = RecordingSession(
        schema_version="1.0",
        selected=1,
        recorded=1,
        skipped=0,
        stopped_early=False,
        recordings=(item,),
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(session.model_dump_json(), encoding="utf-8")


def test_consolidation_ignores_stale_observation_and_binds_current_audio(
    tmp_path: Path,
) -> None:
    root = tmp_path / "speech"
    audio = root / "raw" / "mixed-v2" / "tg_004.wav"
    write_wav(audio, 64_160)
    old_session = root / "recording-sessions" / "old.json"
    new_session = root / "recording-sessions" / "new.json"
    write_session(old_session, observation(37_600, "yes, adha close pannu"))
    write_session(
        new_session,
        observation(64_160, "aaahh, ama adha dha, adha dha close pannu"),
    )

    entries, acoustic, summary = consolidate_dialogue_sessions(
        [build_phase1_dialogue_speech()[3]],
        build_phase1_dialogues(),
        [old_session, new_session],
        root,
    )

    assert entries[0].spoken_reference.startswith("aaahh")
    assert entries[0].audio_sha256 == sha256_file(audio)
    assert entries[0].expected_intent == "approval.confirm"
    assert entries[0].critical_markers == ("affirmation",)
    assert acoustic[0].reference == entries[0].spoken_reference
    assert summary["stale_observations_ignored"] == 1

    manifest = root / "evaluation.jsonl"
    write_evaluation_manifest(entries, manifest)
    assert load_evaluation_manifest(manifest) == entries


def test_consolidation_rejects_conflicting_current_observations(tmp_path: Path) -> None:
    root = tmp_path / "speech"
    write_wav(root / "raw" / "mixed-v2" / "tg_004.wav", 64_160)
    first = root / "sessions" / "first.json"
    second = root / "sessions" / "second.json"
    write_session(first, observation(64_160, "aama adha close pannu"))
    write_session(second, observation(64_160, "yes close pannu"))

    with pytest.raises(ValueError, match="conflicting"):
        consolidate_dialogue_sessions(
            [build_phase1_dialogue_speech()[3]],
            build_phase1_dialogues(),
            [first, second],
            root,
        )


def test_recording_session_rejects_escaping_paths() -> None:
    value = observation(64_160, "aama")
    with pytest.raises(ValueError, match="relative"):
        SessionRecording.model_validate({**value.model_dump(), "path": "../private.wav"})


def test_legacy_session_json_is_strict(tmp_path: Path) -> None:
    path = tmp_path / "invalid.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "selected": 0,
                "recorded": 0,
                "skipped": 0,
                "stopped_early": False,
                "recordings": [],
                "unexpected": True,
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError):
        RecordingSession.model_validate_json(path.read_text(encoding="utf-8"))
