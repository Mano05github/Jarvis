"""Conservative Tanglish normalization, dialogue-state resolution and scoring."""

from __future__ import annotations

import json
import re
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from jarvis.benchmarking.dialogue import DialogueScenario, Scalar
from jarvis.benchmarking.dialogue_session import (
    CriticalMarker,
    DialogueEvaluationEntry,
)

Policy = Literal["none", "allow", "confirm", "deny"]
OwnerAct = Literal["command", "query", "correction", "cancel", "confirm"]

FILLER_RE = re.compile(r"^(?:a+h+|u+h+|u+m+|h+m+)$")
TOKEN_VARIANTS = {
    "ama": "aama",
    "aamaa": "aama",
    "pannidu": "pannu",
    "pannidunga": "pannu",
    "vendaam": "vendam",
    "venam": "vendam",
    "ille": "illa",
    "kaatu": "kaattu",
    "ஆம்": "aama",
    "ஆமா": "aama",
    "ஆமாம்": "aama",
    "இல்லை": "illa",
    "வேண்டாம்": "vendam",
    "ஓபன்": "open",
    "ஓப்பன்": "open",
    "திற": "open",
    "திறந்து": "open",
    "குளோஸ்": "close",
    "மூடு": "close",
    "பண்ணி": "pannu",
    "பண்ணு": "pannu",
    "முன்னாடி": "munnadi",
    "நோட்பேட்": "notepad",
    "கடைசி": "kadaisiya",
    "டவுன்லோட்": "download",
    "பைல்ஸ்": "files",
}


class DialogueState(BaseModel):
    """Typed, non-authoritative state used only to resolve the current turn."""

    model_config = ConfigDict(extra="forbid")

    scenario_id: str
    active_app: str | None = None
    previous_app: str | None = None
    visible_results: str | None = None
    selected_result: int | None = None
    active_document: str | None = None
    last_referenced_entity: str | None = None
    pending_operation: str | None = None
    pending_slots: dict[str, Scalar] = Field(default_factory=dict)
    pending_source_turn: str | None = None
    pending_expires_turn_index: int | None = None
    current_turn_index: int = 0
    previous_owner_turn: str | None = None
    previous_intent: str | None = None
    last_assistant_turn: str | None = None


class SemanticInterpretation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    comparison_text: str
    semantic_text: str
    dialogue_act: OwnerAct
    intent: str
    slots: dict[str, Scalar] = Field(default_factory=dict)
    referents: tuple[str, ...] = ()
    policy: Policy
    critical_markers: tuple[CriticalMarker, ...] = ()
    confidence: float = Field(ge=0, le=1)
    needs_clarification: bool = False


class SemanticSampleResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    utterance_id: str
    input_text: str
    interpretation: SemanticInterpretation
    dialogue_act_match: bool
    intent_match: bool
    slots_match: bool
    referents_match: bool
    markers_preserved: bool
    policy_match: bool
    strict_semantic_success: bool


def comparison_normalize(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text).casefold()
    tokens: list[str] = []
    current: list[str] = []
    for character in normalized.replace("_", " "):
        category = unicodedata.category(character)
        if category[0] in {"L", "M", "N"} or character == "-":
            current.append(character)
        elif current:
            tokens.append("".join(current))
            current.clear()
    if current:
        tokens.append("".join(current))
    canonical: list[str] = []
    for token in tokens:
        token = token.strip("-")
        canonical.append(TOKEN_VARIANTS.get(token, token))
    return " ".join(canonical)


def semantic_normalize(text: str) -> str:
    tokens = comparison_normalize(text).split()
    filtered: list[str] = []
    for token in tokens:
        if FILLER_RE.fullmatch(token):
            continue
        if filtered and filtered[-1] == token:
            continue
        filtered.append(token)
    return " ".join(filtered)


def _contains_any(tokens: set[str], values: tuple[str, ...]) -> bool:
    return any(value in tokens for value in values)


def _detected_markers(
    tokens: set[str], has_replacement_command: bool
) -> tuple[CriticalMarker, ...]:
    markers: list[CriticalMarker] = []
    has_negative = _contains_any(tokens, ("illa", "vendam", "no"))
    if _contains_any(tokens, ("aama", "yes", "okay", "proceed")):
        markers.append("affirmation")
    if "cancel" in tokens or ("vendam" in tokens and not has_replacement_command):
        markers.append("cancellation")
    if has_negative and has_replacement_command:
        markers.append("correction")
    if has_negative:
        markers.append("negation")
    return tuple(markers)


def state_before_turn(scenario: DialogueScenario, turn_id: str) -> DialogueState:
    state = DialogueState(scenario_id=scenario.scenario_id)
    for turn_index, turn in enumerate(scenario.turns):
        if turn.turn_id == turn_id:
            state.current_turn_index = turn_index
            return state
        if turn.speaker == "owner":
            state.previous_owner_turn = turn.turn_id
            state.previous_intent = turn.intent_label
            continue
        state.last_assistant_turn = turn.turn_id
        for key, value in turn.state_updates.items():
            if key == "active_app":
                state.active_app = value if isinstance(value, str) else None
            elif key == "previous_app":
                state.previous_app = value if isinstance(value, str) else None
            elif key == "visible_results":
                state.visible_results = value if isinstance(value, str) else None
            elif key == "selected_index":
                state.selected_result = value if isinstance(value, int) else None
            elif key == "active_document":
                state.active_document = value if isinstance(value, str) else None
        if turn.dialogue_act == "clarify" and state.previous_intent:
            state.pending_operation = state.previous_intent
            state.pending_source_turn = turn.turn_id
            state.pending_expires_turn_index = turn_index + 1
            previous = next(
                (
                    item
                    for item in reversed(scenario.turns[: scenario.turns.index(turn)])
                    if item.speaker == "owner"
                ),
                None,
            )
            if previous is not None:
                state.pending_slots = previous.slots
                symbolic = previous.slots.get("app") or previous.slots.get("target")
                if isinstance(symbolic, str):
                    state.last_referenced_entity = symbolic
    raise ValueError(f"turn not found in scenario: {turn_id}")


def interpret_tanglish(text: str, state: DialogueState) -> SemanticInterpretation:
    comparison = comparison_normalize(text)
    semantic = semantic_normalize(text)
    token_list = semantic.split()
    tokens = set(token_list)
    has_open = "open" in tokens
    has_close = "close" in tokens
    explicit_app: str | None = None
    if "notepad" in tokens or "notepad-ah" in tokens:
        explicit_app = "notepad"
    elif "vs" in tokens and "code" in tokens:
        explicit_app = "visual_studio_code"

    replacement = (has_open and explicit_app is not None) or has_close
    markers = _detected_markers(tokens, replacement)
    correction = "correction" in markers
    affirmation = "affirmation" in markers

    pending_valid = state.pending_operation is not None and (
        state.pending_expires_turn_index is None
        or state.current_turn_index <= state.pending_expires_turn_index
    )
    if affirmation and pending_valid:
        referents = tuple(
            item
            for item in (state.pending_source_turn, state.last_referenced_entity)
            if item is not None
        )
        return SemanticInterpretation(
            comparison_text=comparison,
            semantic_text=semantic,
            dialogue_act="confirm",
            intent="approval.confirm",
            referents=referents,
            policy="allow",
            critical_markers=markers,
            confidence=0.98,
        )

    if has_close and _contains_any(tokens, ("munnadi", "previous")):
        return SemanticInterpretation(
            comparison_text=comparison,
            semantic_text=semantic,
            dialogue_act="correction" if correction else "command",
            intent="app.close",
            slots={"app": "previous_app"},
            referents=("previous_app",),
            policy="allow",
            critical_markers=markers,
            confidence=0.96,
            needs_clarification=state.previous_app is None,
        )

    if has_open and explicit_app is not None:
        referents = (state.previous_owner_turn,) if correction and state.previous_owner_turn else ()
        return SemanticInterpretation(
            comparison_text=comparison,
            semantic_text=semantic,
            dialogue_act="correction" if correction else "command",
            intent="app.open",
            slots={"app": explicit_app},
            referents=referents,
            policy="allow",
            critical_markers=markers,
            confidence=0.98,
        )

    has_download = any(token.startswith("download") for token in tokens)
    latest = _contains_any(tokens, ("latest", "kadaisiya", "recent"))
    if has_download and latest:
        return SemanticInterpretation(
            comparison_text=comparison,
            semantic_text=semantic,
            dialogue_act="command",
            intent="file.search",
            slots={"location": "downloads", "sort": "newest"},
            policy="allow",
            critical_markers=markers,
            confidence=0.94,
        )

    if "cancel" in tokens or "vendam" in tokens:
        return SemanticInterpretation(
            comparison_text=comparison,
            semantic_text=semantic,
            dialogue_act="cancel",
            intent="approval.cancel" if state.pending_operation else "assistant.cancel",
            referents=(state.pending_source_turn,) if state.pending_source_turn else (),
            policy="allow",
            critical_markers=markers,
            confidence=0.90,
        )

    return SemanticInterpretation(
        comparison_text=comparison,
        semantic_text=semantic,
        dialogue_act="query",
        intent="unknown",
        policy="none",
        critical_markers=markers,
        confidence=0.0,
        needs_clarification=True,
    )


def _slots_match(expected: dict[str, Scalar], actual: dict[str, Scalar]) -> bool:
    return all(actual.get(key) == value for key, value in expected.items())


def evaluate_semantics(
    entries: list[DialogueEvaluationEntry],
    scenarios: list[DialogueScenario],
    transcripts: dict[str, str] | None = None,
) -> tuple[list[SemanticSampleResult], dict[str, object]]:
    scenario_map = {scenario.scenario_id: scenario for scenario in scenarios}
    results: list[SemanticSampleResult] = []
    for entry in entries:
        scenario = scenario_map.get(entry.scenario_id)
        if scenario is None:
            raise ValueError(f"missing scenario: {entry.scenario_id}")
        text = (
            transcripts.get(entry.utterance_id, "")
            if transcripts is not None
            else entry.spoken_reference
        )
        interpretation = interpret_tanglish(text, state_before_turn(scenario, entry.turn_id))
        dialogue_act_match = interpretation.dialogue_act == entry.expected_dialogue_act
        intent_match = interpretation.intent == entry.expected_intent
        slots_match = _slots_match(entry.expected_slots, interpretation.slots)
        referents_match = set(entry.expected_referents).issubset(interpretation.referents)
        markers_preserved = set(entry.critical_markers).issubset(interpretation.critical_markers)
        policy_match = interpretation.policy == entry.expected_policy
        strict = all(
            (
                dialogue_act_match,
                intent_match,
                slots_match,
                referents_match,
                markers_preserved,
                policy_match,
                not interpretation.needs_clarification,
            )
        )
        results.append(
            SemanticSampleResult(
                utterance_id=entry.utterance_id,
                input_text=text,
                interpretation=interpretation,
                dialogue_act_match=dialogue_act_match,
                intent_match=intent_match,
                slots_match=slots_match,
                referents_match=referents_match,
                markers_preserved=markers_preserved,
                policy_match=policy_match,
                strict_semantic_success=strict,
            )
        )
    count = len(results)
    slot_results = [
        result for entry, result in zip(entries, results, strict=True) if entry.expected_slots
    ]
    referent_results = [
        result for entry, result in zip(entries, results, strict=True) if entry.expected_referents
    ]
    marker_results = [
        result for entry, result in zip(entries, results, strict=True) if entry.critical_markers
    ]
    summary: dict[str, object] = {
        "schema_version": "1.0",
        "samples": count,
        "strict_semantic_successes": sum(item.strict_semantic_success for item in results),
        "strict_semantic_accuracy": (
            sum(item.strict_semantic_success for item in results) / count if count else 0.0
        ),
        "intent_accuracy": sum(item.intent_match for item in results) / count if count else 0.0,
        "dialogue_act_accuracy": (
            sum(item.dialogue_act_match for item in results) / count if count else 0.0
        ),
        "slot_samples": len(slot_results),
        "slot_accuracy": (
            sum(item.slots_match for item in slot_results) / len(slot_results)
            if slot_results
            else 0.0
        ),
        "referent_samples": len(referent_results),
        "referent_accuracy": (
            sum(item.referents_match for item in referent_results) / len(referent_results)
            if referent_results
            else 0.0
        ),
        "critical_marker_samples": len(marker_results),
        "marker_preservation": (
            sum(item.markers_preserved for item in marker_results) / len(marker_results)
            if marker_results
            else 0.0
        ),
        "policy_accuracy": sum(item.policy_match for item in results) / count if count else 0.0,
        "predicted_intents": dict(Counter(item.interpretation.intent for item in results)),
    }
    return results, summary


def load_transcripts(path: Path) -> dict[str, str]:
    transcripts: dict[str, str] = {}
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        value = json.loads(line)
        utterance_id = value.get("utterance_id")
        transcript = value.get("transcript", value.get("hypothesis"))
        if transcript is None:
            transcript = ""
        if not isinstance(utterance_id, str) or not isinstance(transcript, str):
            raise ValueError(f"invalid transcript record on line {line_number}")
        if utterance_id in transcripts:
            raise ValueError(f"duplicate transcript: {utterance_id}")
        transcripts[utterance_id] = transcript
    return transcripts


def write_semantic_report(
    results: list[SemanticSampleResult], summary: dict[str, object], output: Path
) -> None:
    def metric(name: str) -> float:
        value = summary[name]
        if not isinstance(value, int | float):
            raise TypeError(f"summary metric is not numeric: {name}")
        return float(value)

    output.mkdir(parents=True, exist_ok=True)
    (output / "semantic-results.jsonl").write_text(
        "\n".join(item.model_dump_json() for item in results) + "\n",
        encoding="utf-8",
    )
    (output / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    rows = [
        "# Tanglish semantic evaluation",
        "",
        f"- Samples: {summary['samples']}",
        f"- Strict semantic accuracy: {metric('strict_semantic_accuracy'):.1%}",
        f"- Intent accuracy: {metric('intent_accuracy'):.1%}",
        f"- Dialogue-act accuracy: {metric('dialogue_act_accuracy'):.1%}",
        f"- Slot accuracy: {metric('slot_accuracy'):.1%}",
        f"- Referent accuracy: {metric('referent_accuracy'):.1%}",
        f"- Safety-marker preservation: {metric('marker_preservation'):.1%}",
        f"- Policy accuracy: {metric('policy_accuracy'):.1%}",
        "",
        "| Utterance | Intent | Strict pass |",
        "|---|---|---|",
    ]
    rows.extend(
        f"| {item.utterance_id} | {item.interpretation.intent} | "
        f"{'yes' if item.strict_semantic_success else 'no'} |"
        for item in results
    )
    (output / "report.md").write_text("\n".join(rows) + "\n", encoding="utf-8")
