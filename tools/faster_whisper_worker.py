"""Private line-delimited JSON worker for a resident faster-whisper model."""

from __future__ import annotations

import argparse
import json
import sys
import time
import wave
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import numpy as np


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser()
    value.add_argument("--model", type=Path, required=True)
    value.add_argument("--threads", type=int, default=4)
    value.add_argument("--compute-type", default="int8")
    value.add_argument("--language", choices=("auto", "en", "ta"), default="ta")
    value.add_argument("--hotwords")
    value.add_argument("--beam-size", type=int, default=5)
    value.add_argument("--word-timestamps", action="store_true")
    value.add_argument("--startup-gated", action="store_true")
    return value


def emit(value: object) -> None:
    print(json.dumps(value, ensure_ascii=False), flush=True)


def load_canonical_wav(path: Path) -> np.ndarray:
    """Load the corpus format directly, avoiding version-sensitive PyAV decoding."""
    import numpy as np

    with wave.open(str(path), "rb") as audio:
        channels = audio.getnchannels()
        sample_width = audio.getsampwidth()
        sample_rate = audio.getframerate()
        compression = audio.getcomptype()
        frames = audio.readframes(audio.getnframes())
    if channels != 1 or sample_width != 2 or sample_rate != 16_000 or compression != "NONE":
        raise ValueError("audio must be mono 16-bit PCM WAV at 16000 Hz")
    samples = np.frombuffer(frames, dtype="<i2")
    if samples.size == 0:
        raise ValueError("audio contains no samples")
    return samples.astype(np.float32) / 32_768.0


def main() -> int:
    args = parser().parse_args()
    if args.startup_gated:
        emit({"status": "awaiting_start"})
        line = sys.stdin.readline()
        if not line:
            raise RuntimeError("startup gate closed before authorization")
        request = json.loads(line)
        if not isinstance(request, dict) or request.get("command") != "start":
            raise RuntimeError("startup gate authorization was invalid")
    from faster_whisper import WhisperModel

    started = time.perf_counter()
    model = WhisperModel(
        str(args.model),
        device="cpu",
        compute_type=args.compute_type,
        cpu_threads=args.threads,
        local_files_only=True,
    )
    emit({"status": "ready", "startup_seconds": time.perf_counter() - started})
    for line in sys.stdin:
        request: dict[str, object] = {}
        try:
            request = json.loads(line)
            if request.get("command") == "shutdown":
                emit({"status": "stopped"})
                return 0
            audio = Path(request["audio"])
            if not audio.is_file():
                raise FileNotFoundError(f"audio file not found: {audio}")
            samples = load_canonical_wav(audio)
            started = time.perf_counter()
            segments, info = model.transcribe(
                samples,
                language=None if args.language == "auto" else args.language,
                task="transcribe",
                beam_size=args.beam_size,
                condition_on_previous_text=False,
                vad_filter=False,
                temperature=0.0,
                hotwords=args.hotwords,
                word_timestamps=args.word_timestamps,
            )
            decoded_segments = list(segments)
            text = " ".join(segment.text.strip() for segment in decoded_segments).strip()
            segment_evidence = [
                {
                    "id": segment.id,
                    "start": segment.start,
                    "end": segment.end,
                    "text": segment.text,
                    "avg_logprob": segment.avg_logprob,
                    "no_speech_prob": segment.no_speech_prob,
                    "compression_ratio": segment.compression_ratio,
                    "words": [
                        {
                            "start": word.start,
                            "end": word.end,
                            "word": word.word,
                            "probability": word.probability,
                        }
                        for word in (segment.words or ())
                    ],
                }
                for segment in decoded_segments
            ]
            emit(
                {
                    "status": "completed",
                    "request_id": request["request_id"],
                    "text": text,
                    "language": info.language,
                    "language_probability": info.language_probability,
                    "duration_seconds": info.duration,
                    "duration_after_vad_seconds": info.duration_after_vad,
                    "segments": segment_evidence,
                    "worker_elapsed_seconds": time.perf_counter() - started,
                }
            )
        except Exception as error:
            emit(
                {
                    "status": "failed",
                    "request_id": request.get("request_id") if isinstance(request, dict) else None,
                    "error": f"{type(error).__name__}: {error}",
                }
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
