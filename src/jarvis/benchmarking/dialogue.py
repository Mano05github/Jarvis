"""Versioned dialogue and natural Tanglish speech-corpus models."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Scalar = str | int | float | bool | None


class DialogueTurn(BaseModel):
    """One original owner/assistant turn with its semantic evaluation target."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    turn_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{2,63}$")
    speaker: Literal["owner", "assistant"]
    dialogue_act: Literal[
        "command",
        "query",
        "correction",
        "cancel",
        "confirm",
        "clarify",
        "acknowledge",
        "completion",
        "status",
        "warning",
    ]
    surface_text: str = Field(min_length=1)
    alternate_surfaces: tuple[str, ...] = ()
    intent_label: str | None = None
    slots: dict[str, Scalar] = Field(default_factory=dict)
    refers_to: tuple[str, ...] = ()
    requires_context: bool = False
    expected_policy: Literal["none", "allow", "confirm", "deny"] = "none"
    state_updates: dict[str, Scalar] = Field(default_factory=dict)
    elicitation: str | None = None

    @model_validator(mode="after")
    def validate_role_semantics(self) -> DialogueTurn:
        owner_acts = {"command", "query", "correction", "cancel", "confirm"}
        assistant_acts = {"clarify", "acknowledge", "completion", "status", "warning"}
        if self.speaker == "owner" and self.dialogue_act not in owner_acts:
            raise ValueError("owner turn uses an assistant-only dialogue act")
        if self.speaker == "assistant" and self.dialogue_act not in assistant_acts:
            raise ValueError("assistant turn uses an owner-only dialogue act")
        if self.speaker == "owner" and not self.intent_label:
            raise ValueError("owner turns require an intent_label")
        if self.speaker == "assistant" and self.expected_policy != "none":
            raise ValueError("expected_policy belongs on owner turns")
        return self


class DialogueScenario(BaseModel):
    """An original multi-turn test scenario inspired only by interaction patterns."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"] = "1.0"
    scenario_id: str = Field(pattern=r"^dlg_[0-9]{3}$")
    title: str = Field(min_length=1)
    split: Literal["development", "held-out"]
    mode: Literal["normal", "focused", "urgent", "confirmation-required"]
    initial_state: dict[str, Scalar] = Field(default_factory=dict)
    turns: tuple[DialogueTurn, ...] = Field(min_length=2)
    provenance: Literal["original-pattern-derived"] = "original-pattern-derived"
    provenance_note: str = Field(min_length=20)

    @model_validator(mode="after")
    def validate_turns(self) -> DialogueScenario:
        identifiers = [turn.turn_id for turn in self.turns]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("dialogue scenario contains duplicate turn_id values")
        prefix = f"{self.scenario_id}_t"
        if any(not identifier.startswith(prefix) for identifier in identifiers):
            raise ValueError("turn_id must be namespaced by scenario_id")
        if self.turns[0].speaker != "owner":
            raise ValueError("dialogue scenario must begin with an owner turn")
        if {turn.speaker for turn in self.turns} != {"owner", "assistant"}:
            raise ValueError("dialogue scenario requires both owner and assistant turns")
        for previous, current in zip(self.turns, self.turns[1:], strict=False):
            if previous.speaker == current.speaker:
                raise ValueError("dialogue speakers must alternate")
        return self


class DialogueSpeechEntry(BaseModel):
    """Owner-speech prompt derived from a dialogue turn without embedding movie text."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["2.0"] = "2.0"
    utterance_id: str = Field(pattern=r"^tg_[0-9]{3}$")
    language: Literal["mixed"] = "mixed"
    prompt_mode: Literal["elicited", "exact"] = "elicited"
    reference: str = Field(min_length=1)
    alternate_references: tuple[str, ...] = ()
    elicitation: str = Field(min_length=1)
    intent_label: str = Field(min_length=1)
    scenario_id: str = Field(pattern=r"^dlg_[0-9]{3}$")
    turn_id: str = Field(pattern=r"^dlg_[0-9]{3}_t[0-9]{2}$")
    condition: Literal["quiet-near", "normal-room", "controlled-noise"]
    split: Literal["development", "held-out"]
    audio_file: str = Field(min_length=1)
    consented: Literal[True]
    spoken_reference: str | None = None
    retain_until: str | None = None

    @field_validator("audio_file")
    @classmethod
    def validate_audio_file(cls, value: str) -> str:
        path = Path(value)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("audio_file must be a relative path inside the corpus root")
        if path.suffix.lower() != ".wav":
            raise ValueError("dialogue speech audio must be WAV")
        return value

    @model_validator(mode="after")
    def validate_scenario_link(self) -> DialogueSpeechEntry:
        if not self.turn_id.startswith(f"{self.scenario_id}_t"):
            raise ValueError("turn_id must belong to scenario_id")
        return self


def _load_jsonl[ManifestValue: BaseModel](
    path: Path,
    model_type: type[ManifestValue],
    identifier_of: Callable[[ManifestValue], str],
) -> list[ManifestValue]:
    values: list[ManifestValue] = []
    identifiers: set[str] = set()
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        value = model_type.model_validate_json(line)
        identifier = identifier_of(value)
        if identifier in identifiers:
            raise ValueError(f"duplicate identifier on line {line_number}: {identifier}")
        identifiers.add(identifier)
        values.append(value)
    if not values:
        raise ValueError("manifest is empty")
    return values


def load_dialogues(path: Path) -> list[DialogueScenario]:
    return _load_jsonl(path, DialogueScenario, lambda value: value.scenario_id)


def write_dialogues(scenarios: list[DialogueScenario], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(scenario.model_dump_json() for scenario in scenarios) + "\n",
        encoding="utf-8",
    )


def summarize_dialogues(scenarios: list[DialogueScenario]) -> dict[str, object]:
    turns = [turn for scenario in scenarios for turn in scenario.turns]
    return {
        "scenarios": len(scenarios),
        "turns": len(turns),
        "owner_turns": sum(turn.speaker == "owner" for turn in turns),
        "assistant_turns": sum(turn.speaker == "assistant" for turn in turns),
        "by_split": dict(Counter(scenario.split for scenario in scenarios)),
        "by_mode": dict(Counter(scenario.mode for scenario in scenarios)),
        "by_dialogue_act": dict(Counter(turn.dialogue_act for turn in turns)),
    }


def load_dialogue_speech(path: Path) -> list[DialogueSpeechEntry]:
    return _load_jsonl(path, DialogueSpeechEntry, lambda value: value.utterance_id)


def write_dialogue_speech(entries: list[DialogueSpeechEntry], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(entry.model_dump_json() for entry in entries) + "\n",
        encoding="utf-8",
    )


def summarize_dialogue_speech(entries: list[DialogueSpeechEntry]) -> dict[str, object]:
    return {
        "utterances": len(entries),
        "by_language": dict(Counter(entry.language for entry in entries)),
        "by_condition": dict(Counter(entry.condition for entry in entries)),
        "by_split": dict(Counter(entry.split for entry in entries)),
        "by_prompt_mode": dict(Counter(entry.prompt_mode for entry in entries)),
        "scenarios": len({entry.scenario_id for entry in entries}),
    }
