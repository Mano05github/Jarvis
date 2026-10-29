from pathlib import Path

import pytest
from pydantic import ValidationError

from jarvis.benchmarking.corpus import CorpusEntry, load_corpus, write_corpus


def entry(identifier: str) -> CorpusEntry:
    return CorpusEntry(
        utterance_id=identifier,
        language="mixed",
        reference="Jarvis volume ஐ முப்பதாக வை",
        intent_label="media.volume",
        condition="quiet-near",
        split="development",
        audio_file=f"raw/{identifier}.wav",
        consented=True,
    )


def test_corpus_rejects_escaping_audio_path() -> None:
    with pytest.raises(ValidationError, match="relative path"):
        CorpusEntry.model_validate(
            {**entry("valid_id").model_dump(), "audio_file": "../private.wav"}
        )


def test_corpus_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "corpus.jsonl"
    write_corpus([entry("sample_001")], path)
    assert load_corpus(path) == [entry("sample_001")]


def test_corpus_rejects_duplicate_identifiers(tmp_path: Path) -> None:
    path = tmp_path / "corpus.jsonl"
    write_corpus([entry("sample_001"), entry("sample_001")], path)
    with pytest.raises(ValueError, match="duplicate utterance_id"):
        load_corpus(path)
