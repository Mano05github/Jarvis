from pathlib import Path

import pytest

from jarvis.benchmarking.tts_text import PronunciationLexicon


def write_lexicon(path: Path, *, strict: bool = True) -> None:
    path.write_text(
        'schema_version = "1.0"\n'
        f"reject_unknown_latin = {str(strict).lower()}\n"
        "[replacements]\n"
        '"no problem" = "நோ ப்ராப்ளம்"\n'
        '"problem" = "ப்ராப்ளம்"\n'
        '"open" = "ஓபன்"\n',
        encoding="utf-8",
    )


def test_pronunciation_lexicon_uses_longest_case_insensitive_replacement(
    tmp_path: Path,
) -> None:
    path = tmp_path / "lexicon.toml"
    write_lexicon(path)

    lexicon = PronunciationLexicon.load(path)

    assert lexicon.normalize("சரி, NO PROBLEM. open") == "சரி, நோ ப்ராப்ளம். ஓபன்"


def test_pronunciation_lexicon_rejects_unmapped_latin_terms(tmp_path: Path) -> None:
    path = tmp_path / "lexicon.toml"
    write_lexicon(path)

    with pytest.raises(ValueError, match="unmapped Latin TTS terms: unknown"):
        PronunciationLexicon.load(path).normalize("unknown open")


def test_pronunciation_lexicon_validates_schema_and_entries(tmp_path: Path) -> None:
    path = tmp_path / "lexicon.toml"
    path.write_text(
        'schema_version = "2.0"\n[replacements]\n"open"="ஓபன்"\n',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="unsupported"):
        PronunciationLexicon.load(path)
