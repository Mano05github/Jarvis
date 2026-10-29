import pytest

from jarvis.benchmarking.metrics import (
    char_error_rate,
    edit_distance,
    exact_match,
    word_error_rate,
)


def test_edit_distance() -> None:
    assert edit_distance("kitten", "sitting") == 3


def test_word_error_rate_normalizes_case_and_punctuation() -> None:
    assert word_error_rate("Open Notepad!", "open notepad") == 0


def test_word_error_rate_counts_substitution() -> None:
    assert word_error_rate("open notepad", "open calculator") == pytest.approx(0.5)


def test_char_error_rate_handles_empty_reference() -> None:
    assert char_error_rate("", "") == 0
    assert char_error_rate("", "hello") == 1


def test_exact_match_supports_tamil_unicode() -> None:
    assert exact_match("உலாவியைத் திற", "உலாவியைத் திற")
