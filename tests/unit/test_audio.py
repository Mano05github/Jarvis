import hashlib
import wave
from pathlib import Path

import pytest

from jarvis.benchmarking.audio import normalize_corpus, normalize_wav
from jarvis.benchmarking.corpus import CorpusEntry


def write_quiet_wav(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    samples = b"".join(
        (1_000 if index % 2 else -1_000).to_bytes(2, "little", signed=True)
        for index in range(3_200)
    )
    with wave.open(str(path), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(16_000)
        audio.writeframes(samples)


def corpus_entry() -> CorpusEntry:
    return CorpusEntry(
        utterance_id="en_001",
        language="en",
        reference="Open Notepad",
        intent_label="app.open",
        condition="quiet-near",
        split="development",
        audio_file="raw/en/en_001.wav",
        consented=True,
    )


def test_normalize_wav_preserves_raw_and_applies_bounded_gain(tmp_path: Path) -> None:
    source = tmp_path / "raw.wav"
    destination = tmp_path / "normalized.wav"
    write_quiet_wav(source)
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()

    result = normalize_wav(source, destination, "en_001")

    assert hashlib.sha256(source.read_bytes()).hexdigest() == source_hash
    assert result.gain_db == pytest.approx(8.31, abs=0.1)
    assert result.output_rms_dbfs == pytest.approx(-22.0, abs=0.1)
    assert result.clipped_samples == 0
    with wave.open(str(destination), "rb") as audio:
        assert (audio.getnchannels(), audio.getsampwidth(), audio.getframerate()) == (
            1,
            2,
            16_000,
        )


def test_normalize_corpus_derives_manifest_paths_and_skips_missing(tmp_path: Path) -> None:
    entry = corpus_entry()
    source = tmp_path / entry.audio_file
    write_quiet_wav(source)
    missing = entry.model_copy(update={"utterance_id": "en_002", "audio_file": "raw/en/en_002.wav"})

    derived, results = normalize_corpus([entry, missing], tmp_path, Path("processed/normalized-v1"))

    assert len(results) == 1
    assert derived[0].audio_file == "processed/normalized-v1/en/en_001.wav"
    assert derived[1].audio_file == "processed/normalized-v1/en/en_002.wav"
    assert (tmp_path / derived[0].audio_file).is_file()


def test_normalize_wav_rejects_in_place_processing(tmp_path: Path) -> None:
    source = tmp_path / "raw.wav"
    write_quiet_wav(source)
    with pytest.raises(ValueError, match="must differ"):
        normalize_wav(source, source, "en_001")
