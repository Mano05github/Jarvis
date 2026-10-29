"""Offline verification that does not require third-party dependencies."""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXPECTED_DIRECTORIES = (
    "apps",
    "artifacts",
    "assets/character-references",
    "benchmarks/speech",
    "config/base",
    "config/schemas",
    "config/examples",
    "deliverables/architecture",
    "deliverables/checkpoints",
    "deliverables/decisions",
    "deliverables/manifests",
    "deliverables/plans",
    "deliverables/reports",
    "deliverables/research",
    "native",
    "policies/immutable",
    "policies/privacy",
    "policies/tests",
    "scripts",
    "services",
    "src/jarvis",
    "storage",
    "tests/contract",
    "tests/integration",
    "tests/security",
    "tests/unit",
    "tools",
)
EXPECTED_FILES = (
    ".python-version",
    "pyproject.toml",
    "deliverables/plans/phase-1-plan.md",
    "deliverables/plans/project-structure.md",
    "deliverables/architecture/Jarvis_Architecture_and_Implementation_Plan.docx",
    "deliverables/plans/Jarvis_Implementation_Sprint_Plan_v2.xlsx",
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
    if (ROOT / "docs").exists():
        errors.append("deprecated docs directory exists; use deliverables")

    for path in python_files():
        try:
            ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        except (OSError, SyntaxError, UnicodeError) as error:
            errors.append(f"invalid Python source {path.relative_to(ROOT)}: {error}")

    manifest_path = ROOT / "deliverables/manifests/deliverables_manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("architecture_version") != "1.7":
            errors.append("deliverables manifest does not report architecture 1.7")
    except (OSError, ValueError) as error:
        errors.append(f"invalid deliverables manifest: {error}")
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
