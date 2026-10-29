"""Private line-delimited JSON worker for a local MMS VITS model."""

from __future__ import annotations

import argparse
import json
import sys
import time
import wave
from pathlib import Path

import numpy as np


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser()
    value.add_argument("--model", type=Path, required=True)
    value.add_argument("--threads", type=int, default=4)
    value.add_argument("--seed", type=int, default=7)
    value.add_argument("--speaking-rate", type=float, default=1.0)
    value.add_argument("--noise-scale", type=float, default=0.667)
    value.add_argument("--noise-scale-duration", type=float, default=0.8)
    return value


def emit(value: object) -> None:
    print(json.dumps(value, ensure_ascii=False), flush=True)


def pcm16_bytes(waveform: np.ndarray) -> bytes:
    samples = np.asarray(waveform, dtype=np.float32).reshape(-1)
    if samples.size == 0:
        raise ValueError("model returned no audio samples")
    if not np.isfinite(samples).all():
        raise ValueError("model returned non-finite audio samples")
    return (np.clip(samples, -1.0, 1.0) * 32_767.0).astype("<i2").tobytes()


def write_wav(path: Path, waveform: np.ndarray, sample_rate: int) -> None:
    if not 8_000 <= sample_rate <= 96_000:
        raise ValueError(f"invalid model sample rate: {sample_rate}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".partial")
    with wave.open(str(temporary), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(sample_rate)
        audio.writeframes(pcm16_bytes(waveform))
    temporary.replace(path)


def main() -> int:
    args = parser().parse_args()
    import torch
    from transformers import AutoTokenizer, VitsModel

    torch.set_num_threads(args.threads)
    started = time.perf_counter()
    tokenizer = AutoTokenizer.from_pretrained(str(args.model), local_files_only=True)
    model = VitsModel.from_pretrained(str(args.model), local_files_only=True)
    model.eval()
    model.speaking_rate = args.speaking_rate
    model.noise_scale = args.noise_scale
    model.noise_scale_duration = args.noise_scale_duration
    sample_rate = int(model.config.sampling_rate)
    emit(
        {
            "status": "ready",
            "startup_seconds": time.perf_counter() - started,
            "sample_rate": sample_rate,
        }
    )
    for line in sys.stdin:
        request: dict[str, object] = {}
        try:
            request = json.loads(line)
            if request.get("command") == "shutdown":
                emit({"status": "stopped"})
                return 0
            if request.get("command") != "synthesize":
                raise ValueError("unsupported worker command")
            text = request.get("text")
            output_value = request.get("output")
            if not isinstance(text, str) or not text.strip() or len(text) > 2_000:
                raise ValueError("text must contain 1 to 2000 characters")
            if not isinstance(output_value, str):
                raise ValueError("output must be a path string")
            output = Path(output_value)
            started = time.perf_counter()
            inputs = tokenizer(text, return_tensors="pt")
            torch.manual_seed(args.seed)
            with torch.inference_mode():
                waveform = model(**inputs).waveform.squeeze().cpu().numpy()
            write_wav(output, waveform, sample_rate)
            emit(
                {
                    "status": "completed",
                    "request_id": request["request_id"],
                    "audio_file": str(output.resolve()),
                    "sample_rate": sample_rate,
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
