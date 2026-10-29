"""Offline verification that does not require third-party dependencies."""

from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXPECTED_DIRECTORIES = (
    "apps",
    "benchmarks/speech",
    "config/base",
    "config/examples",
    "native",
    "scripts",
    "services",
    "src/jarvis",
    "storage",
    "tests/contract",
    "tests/unit",
    "tools",
)
EXPECTED_FILES = (
    ".gitignore",
    ".python-version",
    "README.md",
    "pyproject.toml",
    "uv.lock",
)


def python_files() -> list[Path]:
    return sorted(
        path
        for path in ROOT.rglob("*.py")
        if ".venv" not in path.parts
        and "storage" not in path.parts
        and "__pycache__" not in path.parts
    )


def verify() -> list[str]:
    errors: list[str] = []
    if sys.version_info[:3] != (3, 12, 10):
        errors.append(f"expected Python 3.12.10, found {sys.version.split()[0]}")

    for relative in EXPECTED_DIRECTORIES:
        if not (ROOT / relative).is_dir():
            errors.append(f"missing directory: {relative}")
    for relative in EXPECTED_FILES:
        if not (ROOT / relative).is_file():
            errors.append(f"missing file: {relative}")
    for path in python_files():
        try:
            ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        except (OSError, SyntaxError, UnicodeError) as error:
            errors.append(f"invalid Python source {path.relative_to(ROOT)}: {error}")

    return errors


def main() -> int:
    errors = verify()
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print(f"Offline workspace verification passed ({len(python_files())} Python files).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
