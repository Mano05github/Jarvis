from jarvis.benchmarking.dialogue_pack import (
    build_phase1_dialogue_speech,
    build_phase1_dialogues,
)
from jarvis.benchmarking.dialogue_session import DialogueEvaluationEntry
from jarvis.benchmarking.tanglish_semantics import (
    DialogueState,
    comparison_normalize,
    evaluate_semantics,
    interpret_tanglish,
    load_transcripts,
    semantic_normalize,
    state_before_turn,
)

SPOKEN = (
    "jarvis, notepad -ah open pannu",
    "illa vendam, VS Code Open pannu",
    "idhuku munnadi open pannadha close pannidu",
    "aaahh, ama adha dha,.. adha dha close pannu",
    "kadaisiya download aana files la ennanu naa paakanum",
)


def pilot_entries() -> list[DialogueEvaluationEntry]:
    scenarios = build_phase1_dialogues()
    turns = {turn.turn_id: turn for scenario in scenarios for turn in scenario.turns}
    entries: list[DialogueEvaluationEntry] = []
    for prompt, spoken in zip(build_phase1_dialogue_speech()[:5], SPOKEN, strict=True):
        turn = turns[prompt.turn_id]
        markers: tuple[str, ...] = ()
        if turn.dialogue_act == "correction":
            markers = ("correction", "negation")
        elif turn.dialogue_act == "confirm":
            markers = ("affirmation",)
        entries.append(
            DialogueEvaluationEntry(
                utterance_id=prompt.utterance_id,
                scenario_id=prompt.scenario_id,
                turn_id=prompt.turn_id,
                condition=prompt.condition,
                split=prompt.split,
                audio_file=prompt.audio_file,
                audio_sha256="0" * 64,
                spoken_reference=spoken,
                expected_dialogue_act=turn.dialogue_act,
                expected_intent=turn.intent_label or "unknown",
                expected_slots=turn.slots,
                expected_referents=turn.refers_to,
                expected_policy=turn.expected_policy,
                requires_context=turn.requires_context,
                critical_markers=markers,
                source_session="recording-sessions/pilot.json",
            )
        )
    return entries


def test_normalization_removes_fillers_but_preserves_safety_words() -> None:
    text = "Aaahh... illa, vendam, VS Code open pannu pannu"
    assert comparison_normalize(text) == "aaahh illa vendam vs code open pannu pannu"
    assert semantic_normalize(text) == "illa vendam vs code open pannu"


def test_normalization_preserves_tamil_graphemes_and_maps_core_meaning() -> None:
    text = "ஆமா, வேண்டாம்; முன்னாடி ஓபன் பண்ணியதை குளோஸ் பண்ணு"

    assert comparison_normalize(text) == ("aama vendam munnadi open பண்ணியதை close pannu")


def test_deterministic_parser_passes_all_five_owner_references() -> None:
    results, summary = evaluate_semantics(pilot_entries(), build_phase1_dialogues())

    assert summary["strict_semantic_accuracy"] == 1.0
    assert summary["intent_accuracy"] == 1.0
    assert summary["marker_preservation"] == 1.0
    assert all(item.strict_semantic_success for item in results)


def test_correction_supersedes_previous_owner_turn() -> None:
    scenario = build_phase1_dialogues()[0]
    state = state_before_turn(scenario, "dlg_001_t03")
    result = interpret_tanglish("illa vendam, VS Code open pannu", state)

    assert result.dialogue_act == "correction"
    assert result.intent == "app.open"
    assert result.slots == {"app": "visual_studio_code"}
    assert result.referents == ("dlg_001_t01",)
    assert set(result.critical_markers) == {"correction", "negation"}


def test_confirmation_is_bound_to_pending_operation() -> None:
    scenario = build_phase1_dialogues()[0]
    state = state_before_turn(scenario, "dlg_001_t07")
    result = interpret_tanglish("yes, adha close pannu", state)

    assert result.intent == "approval.confirm"
    assert result.referents == ("dlg_001_t06", "previous_app")
    assert result.needs_clarification is False


def test_tamil_script_confirmation_is_bound_to_pending_operation() -> None:
    scenario = build_phase1_dialogues()[0]
    state = state_before_turn(scenario, "dlg_001_t07")
    result = interpret_tanglish("ஆமா ஆமா", state)

    assert result.intent == "approval.confirm"
    assert result.critical_markers == ("affirmation",)


def test_expired_confirmation_is_not_accepted() -> None:
    state = DialogueState(
        scenario_id="dlg_999",
        pending_operation="file.delete",
        pending_source_turn="dlg_999_t02",
        pending_expires_turn_index=2,
        current_turn_index=3,
    )
    result = interpret_tanglish("aama proceed pannu", state)
    assert result.intent == "unknown"
    assert result.needs_clarification is True


def test_contextual_close_requires_known_previous_app() -> None:
    state = DialogueState(scenario_id="dlg_999")
    result = interpret_tanglish("munnadi open pannadha close pannu", state)
    assert result.intent == "app.close"
    assert result.needs_clarification is True


def test_unknown_text_requires_clarification() -> None:
    result = interpret_tanglish("enna idhu", DialogueState(scenario_id="dlg_999"))
    assert result.intent == "unknown"
    assert result.needs_clarification is True


def test_stt_sample_hypotheses_load_as_semantic_transcripts(tmp_path) -> None:
    path = tmp_path / "samples.jsonl"
    path.write_text(
        '{"utterance_id":"tg_001","hypothesis":"notepad open pannu"}\n'
        '{"utterance_id":"tg_002","hypothesis":null}\n',
        encoding="utf-8",
    )
    assert load_transcripts(path) == {
        "tg_001": "notepad open pannu",
        "tg_002": "",
    }
