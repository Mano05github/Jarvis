from pathlib import Path

import pytest
from pydantic import ValidationError

from jarvis.benchmarking.dialogue import (
    DialogueScenario,
    DialogueSpeechEntry,
    DialogueTurn,
    load_dialogue_speech,
    load_dialogues,
    summarize_dialogue_speech,
    summarize_dialogues,
    write_dialogue_speech,
    write_dialogues,
)
from jarvis.benchmarking.dialogue_pack import (
    build_phase1_dialogue_speech,
    build_phase1_dialogues,
)


def test_dialogue_pack_covers_context_and_safety_without_split_leakage() -> None:
    scenarios = build_phase1_dialogues()
    summary = summarize_dialogues(scenarios)
    turns = [turn for scenario in scenarios for turn in scenario.turns]

    assert summary["scenarios"] == 10
    assert summary["turns"] == 80
    assert summary["owner_turns"] == 40
    assert summary["assistant_turns"] == 40
    assert summary["by_split"] == {"development": 8, "held-out": 2}
    assert {turn.dialogue_act for turn in turns} >= {
        "command",
        "correction",
        "cancel",
        "clarify",
        "warning",
        "completion",
    }
    assert any(turn.requires_context for turn in turns)
    assert any(turn.expected_policy == "confirm" for turn in turns)
    assert all(scenario.provenance == "original-pattern-derived" for scenario in scenarios)


def test_dialogue_speech_pack_has_natural_owner_prompts_and_scenario_splits() -> None:
    scenarios = {item.scenario_id: item for item in build_phase1_dialogues()}
    entries = build_phase1_dialogue_speech()

    assert summarize_dialogue_speech(entries) == {
        "utterances": 40,
        "by_language": {"mixed": 40},
        "by_condition": {
            "quiet-near": 16,
            "normal-room": 16,
            "controlled-noise": 8,
        },
        "by_split": {"development": 32, "held-out": 8},
        "by_prompt_mode": {"elicited": 40},
        "scenarios": 10,
    }
    assert len({entry.reference.casefold() for entry in entries}) == 40
    assert all(entry.split == scenarios[entry.scenario_id].split for entry in entries)
    assert entries[0].reference == "Jarvis, notepad-ah open pannu"


def test_dialogue_manifests_round_trip(tmp_path: Path) -> None:
    dialogue_path = tmp_path / "dialogues.jsonl"
    speech_path = tmp_path / "speech.jsonl"
    scenarios = build_phase1_dialogues()
    entries = build_phase1_dialogue_speech()

    write_dialogues(scenarios, dialogue_path)
    write_dialogue_speech(entries, speech_path)

    assert load_dialogues(dialogue_path) == scenarios
    assert load_dialogue_speech(speech_path) == entries


def test_dialogue_rejects_non_alternating_speakers() -> None:
    owner = DialogueTurn(
        turn_id="dlg_999_t01",
        speaker="owner",
        dialogue_act="command",
        surface_text="Notepad open pannu",
        intent_label="app.open",
    )
    assistant = DialogueTurn(
        turn_id="dlg_999_t02",
        speaker="assistant",
        dialogue_act="completion",
        surface_text="Opened.",
    )
    with pytest.raises(ValidationError, match="alternate"):
        DialogueScenario(
            scenario_id="dlg_999",
            title="Invalid",
            split="development",
            mode="normal",
            turns=(
                owner,
                assistant,
                assistant.model_copy(update={"turn_id": "dlg_999_t03"}),
            ),
            provenance_note="This is an original invalid test scenario and not a transcript.",
        )


@pytest.mark.parametrize(
    ("values", "message"),
    [
        (
            {
                "turn_id": "dlg_999_t01",
                "speaker": "owner",
                "dialogue_act": "warning",
                "surface_text": "Warning",
                "intent_label": "system.warning",
            },
            "assistant-only",
        ),
        (
            {
                "turn_id": "dlg_999_t01",
                "speaker": "owner",
                "dialogue_act": "command",
                "surface_text": "Open it",
            },
            "intent_label",
        ),
        (
            {
                "turn_id": "dlg_999_t02",
                "speaker": "assistant",
                "dialogue_act": "command",
                "surface_text": "Open it",
            },
            "owner-only",
        ),
        (
            {
                "turn_id": "dlg_999_t02",
                "speaker": "assistant",
                "dialogue_act": "completion",
                "surface_text": "Done",
                "expected_policy": "confirm",
            },
            "owner turns",
        ),
    ],
)
def test_dialogue_turn_rejects_role_semantic_mismatches(
    values: dict[str, object], message: str
) -> None:
    with pytest.raises(ValidationError, match=message):
        DialogueTurn.model_validate(values)


def test_dialogue_speech_rejects_escaping_and_cross_scenario_links() -> None:
    valid = DialogueSpeechEntry(
        utterance_id="tg_001",
        reference="Notepad open pannu",
        elicitation="Open Notepad naturally.",
        intent_label="app.open",
        scenario_id="dlg_001",
        turn_id="dlg_001_t01",
        condition="quiet-near",
        split="development",
        audio_file="raw/mixed-v2/tg_001.wav",
        consented=True,
    )
    with pytest.raises(ValidationError, match="relative path"):
        DialogueSpeechEntry.model_validate({**valid.model_dump(), "audio_file": "../tg_001.wav"})
    with pytest.raises(ValidationError, match="belong"):
        DialogueSpeechEntry.model_validate({**valid.model_dump(), "turn_id": "dlg_002_t01"})


def test_dialogue_loader_rejects_empty_and_duplicate_manifests(tmp_path: Path) -> None:
    empty = tmp_path / "empty.jsonl"
    empty.write_text("\n", encoding="utf-8")
    with pytest.raises(ValueError, match="empty"):
        load_dialogues(empty)

    duplicate = tmp_path / "duplicate.jsonl"
    scenario = build_phase1_dialogues()[0]
    duplicate.write_text(
        f"{scenario.model_dump_json()}\n{scenario.model_dump_json()}\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="duplicate"):
        load_dialogues(duplicate)
