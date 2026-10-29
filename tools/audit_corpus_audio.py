"""Print privacy-safe signal-level diagnostics for recorded corpus WAV files."""

from __future__ import annotations

import argparse
import array
import json
import math
import statistics
import sys
import wave
from collections import defaultdict
from pathlib import Path


def analyze(path: Path) -> dict[str, float]:
    with wave.open(str(path), "rb") as audio:
        frames = audio.getnframes()
        sample_rate = audio.getframerate()
        samples = array.array("h", audio.readframes(frames))
    if sys.byteorder != "little":
        samples.byteswap()
    count = max(1, len(samples))
    rms = math.sqrt(sum(sample * sample for sample in samples) / count)
    peak = max((abs(sample) for sample in samples), default=0)
    clipped = sum(abs(sample) >= 32_760 for sample in samples)
    return {
        "duration_seconds": frames / sample_rate,
        "rms_dbfs": 20 * math.log10(max(1.0, rms) / 32_768),
        "peak_dbfs": 20 * math.log10(max(1, peak) / 32_768),
        "clip_percent": 100 * clipped / count,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    parser.add_argument("corpus_root", type=Path)
    args = parser.parse_args()
    root = args.corpus_root.resolve()
    entries = [
        json.loads(line)
        for line in args.manifest.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    rows: list[dict[str, object]] = []
    for entry in entries:
        path = (root / entry["audio_file"]).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            continue
        rows.append(
            {
                "utterance_id": entry["utterance_id"],
                "condition": entry["condition"],
                **analyze(path),
            }
        )

    grouped: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        grouped[str(row["condition"])].append(row)
    by_condition: dict[str, object] = {}
    for condition, items in grouped.items():
        levels = [float(item["rms_dbfs"]) for item in items]
        clipping = [float(item["clip_percent"]) for item in items]
        by_condition[condition] = {
            "files": len(items),
            "median_rms_dbfs": round(statistics.median(levels), 2),
            "min_rms_dbfs": round(min(levels), 2),
            "max_rms_dbfs": round(max(levels), 2),
            "max_clip_percent": round(max(clipping), 4),
        }
    outliers = [
        {
            "utterance_id": item["utterance_id"],
            "condition": item["condition"],
            "rms_dbfs": round(float(item["rms_dbfs"]), 2),
            "peak_dbfs": round(float(item["peak_dbfs"]), 2),
            "clip_percent": round(float(item["clip_percent"]), 4),
        }
        for item in rows
        if float(item["rms_dbfs"]) < -35
        or float(item["rms_dbfs"]) > -9
        or float(item["clip_percent"]) > 0.1
    ]
    print(
        json.dumps(
            {"files": len(rows), "by_condition": by_condition, "level_outliers": outliers},
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
