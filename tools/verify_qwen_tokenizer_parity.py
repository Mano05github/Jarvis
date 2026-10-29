"""Compare the retained Hugging Face tokenizer with the tokenizer embedded in GGUF."""

from __future__ import annotations

import argparse
import ast
import json
import subprocess
from pathlib import Path
from typing import Any

from transformers import AutoTokenizer


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tokenizer-dir", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--tokenizer-executable", type=Path, required=True)
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def _gguf_token_ids(executable: Path, model: Path, text: str) -> list[int]:
    completed = subprocess.run(
        [
            str(executable),
            "--model",
            str(model),
            "--stdin",
            "--ids",
            "--no-parse-special",
            "--log-disable",
        ],
        input=text.encode("utf-8"),
        capture_output=True,
        check=False,
        shell=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            "llama-tokenize failed: " + completed.stderr.decode("utf-8", errors="replace").strip()
        )
    output = completed.stdout.decode("utf-8", errors="strict").strip()
    token_ids = ast.literal_eval(output)
    if not isinstance(token_ids, list) or not all(
        isinstance(token_id, int) for token_id in token_ids
    ):
        raise ValueError(f"unexpected llama-tokenize output: {output}")
    return token_ids


def _case_texts(path: Path) -> list[tuple[str, str]]:
    texts: list[tuple[str, str]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        if not line.strip():
            continue
        payload: dict[str, Any] = json.loads(line)
        case_id = payload.get("case_id")
        hypothesis = payload.get("hypothesis")
        if not isinstance(case_id, str) or not isinstance(hypothesis, str):
            raise ValueError(f"invalid case on line {line_number}")
        texts.append((case_id, hypothesis))
    if not texts:
        raise ValueError("tokenizer parity case pack is empty")
    return texts


def main() -> int:
    args = _arguments()
    for label, path in (
        ("tokenizer directory", args.tokenizer_dir),
        ("GGUF model", args.model),
        ("llama tokenizer", args.tokenizer_executable),
        ("case pack", args.cases),
    ):
        if not path.exists():
            raise FileNotFoundError(f"{label} not found: {path}")

    tokenizer = AutoTokenizer.from_pretrained(
        args.tokenizer_dir,
        local_files_only=True,
        trust_remote_code=False,
        fix_mistral_regex=True,
    )
    cases = _case_texts(args.cases)
    probe = "\n".join(f"{case_id}\t{text}" for case_id, text in cases)
    hf_ids = tokenizer.encode(probe, add_special_tokens=False)
    gguf_ids = _gguf_token_ids(args.tokenizer_executable, args.model, probe)
    parity_pass = hf_ids == gguf_ids

    first_mismatch = next(
        (
            index
            for index, pair in enumerate(zip(hf_ids, gguf_ids, strict=False))
            if pair[0] != pair[1]
        ),
        None,
    )
    if first_mismatch is None and len(hf_ids) != len(gguf_ids):
        first_mismatch = min(len(hf_ids), len(gguf_ids))
    report = {
        "schema_version": "1.0",
        "fix_mistral_regex": True,
        "cases_in_probe": len(cases),
        "hf_tokens": len(hf_ids),
        "gguf_tokens": len(gguf_ids),
        "first_mismatch_index": first_mismatch,
        "parity_pass": parity_pass,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["parity_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
