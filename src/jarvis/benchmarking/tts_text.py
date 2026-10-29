"""Strict editable text normalization for limited-vocabulary TTS fallbacks."""

from __future__ import annotations

import re
import tomllib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

_LATIN_WORD = re.compile(r"[A-Za-z]+(?:['-][A-Za-z]+)*")


def _literal_replacement(value: str) -> Callable[[re.Match[str]], str]:
    def replace(_match: re.Match[str]) -> str:
        return value

    return replace


@dataclass(frozen=True, slots=True)
class PronunciationLexicon:
    replacements: tuple[tuple[str, str], ...]
    reject_unknown_latin: bool = True

    @classmethod
    def load(cls, path: Path) -> PronunciationLexicon:
        value = tomllib.loads(path.read_text(encoding="utf-8"))
        schema_version = value.get("schema_version")
        if schema_version != "1.0":
            raise ValueError(f"unsupported pronunciation lexicon schema: {schema_version}")
        raw = value.get("replacements")
        if not isinstance(raw, dict) or not raw:
            raise ValueError("pronunciation lexicon must contain replacements")
        replacements: list[tuple[str, str]] = []
        for source, destination in raw.items():
            if not isinstance(source, str) or not source.strip():
                raise ValueError("pronunciation source must be non-empty text")
            if not isinstance(destination, str) or not destination.strip():
                raise ValueError(f"pronunciation replacement is empty: {source}")
            replacements.append((source, destination))
        replacements.sort(key=lambda item: len(item[0]), reverse=True)
        strict = value.get("reject_unknown_latin", True)
        if not isinstance(strict, bool):
            raise ValueError("reject_unknown_latin must be boolean")
        return cls(tuple(replacements), strict)

    def normalize(self, text: str) -> str:
        normalized = text
        for source, destination in self.replacements:
            pattern = re.compile(
                rf"(?<![A-Za-z]){re.escape(source)}(?![A-Za-z])",
                flags=re.IGNORECASE,
            )
            normalized = pattern.sub(_literal_replacement(destination), normalized)
        unknown = sorted({match.group(0) for match in _LATIN_WORD.finditer(normalized)})
        if self.reject_unknown_latin and unknown:
            raise ValueError(f"unmapped Latin TTS terms: {', '.join(unknown)}")
        return re.sub(r"\s+", " ", normalized).strip()
