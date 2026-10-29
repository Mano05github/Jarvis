from __future__ import annotations

import importlib.util
import wave
from pathlib import Path
from types import ModuleType

import numpy as np
import pytest


def load_worker_tool() -> ModuleType:
    path = Path(__file__).parents[2] / "tools" / "mms_vits_worker.py"
    spec = importlib.util.spec_from_file_location("mms_vits_worker_tool", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_pcm16_bytes_clips_and_rejects_bad_audio() -> None:
    module = load_worker_tool()
    samples = np.frombuffer(
        module.pcm16_bytes(np.array([-2.0, 0.0, 2.0], dtype=np.float32)), dtype="<i2"
    )

    assert samples.tolist() == [-32767, 0, 32767]
    with pytest.raises(ValueError, match="no audio"):
        module.pcm16_bytes(np.array([], dtype=np.float32))
    with pytest.raises(ValueError, match="non-finite"):
        module.pcm16_bytes(np.array([np.nan], dtype=np.float32))


def test_write_wav_creates_canonical_mono_pcm(tmp_path: Path) -> None:
    module = load_worker_tool()
    output = tmp_path / "sample.wav"

    module.write_wav(output, np.zeros(100, dtype=np.float32), 16_000)

    with wave.open(str(output), "rb") as audio:
        assert audio.getnchannels() == 1
        assert audio.getsampwidth() == 2
        assert audio.getframerate() == 16_000
        assert audio.getnframes() == 100
    with pytest.raises(ValueError, match="sample rate"):
        module.write_wav(output, np.zeros(1, dtype=np.float32), 100)
