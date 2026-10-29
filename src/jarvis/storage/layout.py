"""Safe resolution of all machine-local Jarvis data paths."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


class StorageBoundaryError(ValueError):
    """Raised when a path escapes the configured Jarvis storage root."""


AREAS = (
    "models",
    "engines",
    "datasets",
    "benchmarks",
    "audit",
    "cache",
    "temp",
    "secrets",
)


def project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def configured_storage_root() -> Path:
    configured = os.environ.get("JARVIS_STORAGE_ROOT")
    return Path(configured).expanduser() if configured else project_root() / "storage"


@dataclass(frozen=True, slots=True)
class StorageLayout:
    root: Path

    @classmethod
    def from_environment(cls) -> StorageLayout:
        return cls(configured_storage_root().resolve())

    def initialize(self) -> None:
        for area in AREAS:
            (self.root / area).mkdir(parents=True, exist_ok=True)

    def path(self, area: str, *parts: str, create_parent: bool = False) -> Path:
        if area not in AREAS:
            raise StorageBoundaryError(f"unknown storage area: {area}")
        if any(not part or Path(part).is_absolute() or ".." in Path(part).parts for part in parts):
            raise StorageBoundaryError("storage paths must use non-empty relative parts")

        base = (self.root / area).resolve()
        candidate = base.joinpath(*parts).resolve(strict=False)
        if not candidate.is_relative_to(base):
            raise StorageBoundaryError(f"path escapes {area} storage: {candidate}")
        if create_parent:
            candidate.parent.mkdir(parents=True, exist_ok=True)
        return candidate

