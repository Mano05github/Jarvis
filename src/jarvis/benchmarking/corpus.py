"""Validated, privacy-aware speech corpus manifests."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class CorpusEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"] = "1.0"
    utterance_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{2,63}$")
    language: Literal["ta", "en", "mixed"]
    reference: str = Field(min_length=1)
    intent_label: str = Field(min_length=1)
    condition: Literal["quiet-near", "normal-room", "controlled-noise"]
    split: Literal["development", "held-out"]
    audio_file: str = Field(min_length=1)
    consented: Literal[True]
    retain_until: str | None = None

    @field_validator("audio_file")
    @classmethod
    def validate_audio_file(cls, value: str) -> str:
        path = Path(value)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("audio_file must be a relative path inside the corpus root")
        if path.suffix.lower() not in {".wav", ".flac"}:
            raise ValueError("audio_file must be WAV or FLAC")
        return value


def load_corpus(path: Path) -> list[CorpusEntry]:
    entries: list[CorpusEntry] = []
    identifiers: set[str] = set()
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        entry = CorpusEntry.model_validate_json(line)
        if entry.utterance_id in identifiers:
            raise ValueError(f"duplicate utterance_id on line {line_number}: {entry.utterance_id}")
        identifiers.add(entry.utterance_id)
        entries.append(entry)
    if not entries:
        raise ValueError("corpus manifest is empty")
    return entries


def summarize_corpus(entries: list[CorpusEntry]) -> dict[str, object]:
    return {
        "utterances": len(entries),
        "by_language": dict(Counter(entry.language for entry in entries)),
        "by_condition": dict(Counter(entry.condition for entry in entries)),
        "by_split": dict(Counter(entry.split for entry in entries)),
    }


def write_corpus(entries: list[CorpusEntry], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = "\n".join(entry.model_dump_json() for entry in entries) + "\n"
    path.write_text(content, encoding="utf-8")
