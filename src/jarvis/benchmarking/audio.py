"""Privacy-safe, non-destructive corpus audio preprocessing."""

from __future__ import annotations

import array
import math
import sys
import wave
from dataclasses import dataclass
from pathlib import Path

from jarvis.benchmarking.corpus import CorpusEntry


@dataclass(frozen=True, slots=True)
class NormalizationResult:
    utterance_id: str
    input_rms_dbfs: float
    output_rms_dbfs: float
    input_peak_dbfs: float
    output_peak_dbfs: float
    gain_db: float
    clipped_samples: int


def _dbfs(value: float) -> float:
    return 20 * math.log10(max(1.0, value) / 32_768)


def _rms(samples: array.array[int]) -> float:
    if not samples:
        return 0.0
    return math.sqrt(sum(sample * sample for sample in samples) / len(samples))


def normalize_wav(
    source: Path,
    destination: Path,
    utterance_id: str,
    *,
    target_rms_dbfs: float = -22.0,
    peak_ceiling_dbfs: float = -3.0,
    max_gain_db: float = 20.0,
) -> NormalizationResult:
    """Normalize a PCM WAV with bounded gain while preserving the raw source."""
    if source.resolve() == destination.resolve():
        raise ValueError("normalization destination must differ from the source")
    with wave.open(str(source), "rb") as audio:
        channels = audio.getnchannels()
        width = audio.getsampwidth()
        rate = audio.getframerate()
        compression = audio.getcomptype()
        frames = audio.getnframes()
        samples = array.array("h", audio.readframes(frames))
    if channels != 1 or width != 2 or rate != 16_000 or compression != "NONE":
        raise ValueError("normalization requires mono 16-bit PCM WAV at 16000 Hz")
    if sys.byteorder != "little":
        samples.byteswap()
    if not samples:
        raise ValueError("normalization source contains no samples")

    mean = sum(samples) / len(samples)
    centered = array.array("h", (round(sample - mean) for sample in samples))
    input_rms = _rms(centered)
    input_peak = max(abs(sample) for sample in centered)
    target_rms = 32_768 * 10 ** (target_rms_dbfs / 20)
    peak_ceiling = 32_768 * 10 ** (peak_ceiling_dbfs / 20)
    rms_gain = target_rms / max(1.0, input_rms)
    peak_gain = peak_ceiling / max(1, input_peak)
    maximum_gain = 10 ** (max_gain_db / 20)
    gain = min(rms_gain, peak_gain, maximum_gain)

    clipped = 0
    normalized = array.array("h")
    for sample in centered:
        scaled = round(sample * gain)
        bounded = max(-32_768, min(32_767, scaled))
        clipped += bounded != scaled
        normalized.append(bounded)
    output_rms = _rms(normalized)
    output_peak = max(abs(sample) for sample in normalized)
    if sys.byteorder != "little":
        normalized.byteswap()

    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_name(f"{destination.name}.partial")
    with wave.open(str(partial), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(16_000)
        output.writeframes(normalized.tobytes())
    partial.replace(destination)
    return NormalizationResult(
        utterance_id=utterance_id,
        input_rms_dbfs=_dbfs(input_rms),
        output_rms_dbfs=_dbfs(output_rms),
        input_peak_dbfs=_dbfs(input_peak),
        output_peak_dbfs=_dbfs(output_peak),
        gain_db=20 * math.log10(gain),
        clipped_samples=clipped,
    )


def normalize_corpus(
    entries: list[CorpusEntry],
    corpus_root: Path,
    output_prefix: Path,
) -> tuple[list[CorpusEntry], list[NormalizationResult]]:
    """Create normalized derivatives and a matching manifest entry set."""
    root = corpus_root.resolve()
    if output_prefix.is_absolute() or ".." in output_prefix.parts:
        raise ValueError("output prefix must stay relative to the corpus root")
    derived: list[CorpusEntry] = []
    results: list[NormalizationResult] = []
    for entry in entries:
        source = (root / entry.audio_file).resolve()
        relative_output = output_prefix / entry.language / f"{entry.utterance_id}.wav"
        destination = (root / relative_output).resolve()
        if not source.is_relative_to(root) or not destination.is_relative_to(root):
            raise ValueError("corpus audio path escapes the corpus root")
        derived.append(entry.model_copy(update={"audio_file": relative_output.as_posix()}))
        if source.is_file():
            results.append(normalize_wav(source, destination, entry.utterance_id))
    return derived, results
