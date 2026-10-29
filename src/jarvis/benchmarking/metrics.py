"""Dependency-light accuracy metrics for STT certification."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence


def normalize_text(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text).casefold()
    normalized = re.sub(r"[^\w\s]", " ", normalized, flags=re.UNICODE)
    return " ".join(normalized.split())


def edit_distance[T](reference: Sequence[T], hypothesis: Sequence[T]) -> int:
    previous = list(range(len(hypothesis) + 1))
    for reference_index, reference_item in enumerate(reference, 1):
        current = [reference_index]
        for hypothesis_index, hypothesis_item in enumerate(hypothesis, 1):
            substitution = previous[hypothesis_index - 1] + (reference_item != hypothesis_item)
            current.append(
                min(
                    previous[hypothesis_index] + 1,
                    current[hypothesis_index - 1] + 1,
                    substitution,
                )
            )
        previous = current
    return previous[-1]


def _error_rate[T](reference: Sequence[T], hypothesis: Sequence[T]) -> float:
    if not reference:
        return 0.0 if not hypothesis else 1.0
    return edit_distance(reference, hypothesis) / len(reference)


def word_error_rate(reference: str, hypothesis: str) -> float:
    return _error_rate(normalize_text(reference).split(), normalize_text(hypothesis).split())


def char_error_rate(reference: str, hypothesis: str) -> float:
    return _error_rate(list(normalize_text(reference)), list(normalize_text(hypothesis)))


def exact_match(reference: str, hypothesis: str) -> bool:
    return normalize_text(reference) == normalize_text(hypothesis)
