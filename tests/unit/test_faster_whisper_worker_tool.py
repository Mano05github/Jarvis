from __future__ import annotations

import importlib.util
import wave
from pathlib import Path
from types import ModuleType

import numpy as np
import pytest


def load_worker_tool() -> ModuleType:
    path = Path(__file__).parents[2] / "tools" / "faster_whisper_worker.py"
    spec = importlib.util.spec_from_file_location("faster_whisper_worker_tool", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_wav(path: Path, *, rate: int = 16_000, channels: int = 1) -> None:
    samples = np.array([-16_384, 0, 16_384], dtype="<i2")
    with wave.open(str(path), "wb") as audio:
        audio.setnchannels(channels)
        audio.setsampwidth(2)
        audio.setframerate(rate)
        audio.writeframes(samples.tobytes())


def test_load_canonical_wav_returns_float_samples(tmp_path: Path) -> None:
    module = load_worker_tool()
    path = tmp_path / "sample.wav"
    write_wav(path)

    samples = module.load_canonical_wav(path)

    assert samples.dtype == np.float32
    assert samples.tolist() == pytest.approx([-0.5, 0.0, 0.5])


@pytest.mark.parametrize(("rate", "channels"), [(8_000, 1), (16_000, 2)])
def test_load_canonical_wav_rejects_wrong_format(tmp_path: Path, rate: int, channels: int) -> None:
    module = load_worker_tool()
    path = tmp_path / "invalid.wav"
    write_wav(path, rate=rate, channels=channels)

    with pytest.raises(ValueError, match="mono 16-bit PCM"):
        module.load_canonical_wav(path)
