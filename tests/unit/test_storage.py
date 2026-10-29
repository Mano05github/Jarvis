from pathlib import Path

import pytest

from jarvis.storage import AREAS, StorageBoundaryError, StorageLayout


def test_initialize_creates_all_areas(tmp_path: Path) -> None:
    layout = StorageLayout(tmp_path / "storage")
    layout.initialize()
    assert all((layout.root / area).is_dir() for area in AREAS)


def test_path_rejects_traversal(tmp_path: Path) -> None:
    layout = StorageLayout(tmp_path / "storage")
    with pytest.raises(StorageBoundaryError):
        layout.path("models", "..", "outside.bin")


def test_path_rejects_absolute_parts(tmp_path: Path) -> None:
    layout = StorageLayout(tmp_path / "storage")
    with pytest.raises(StorageBoundaryError):
        layout.path("models", str((tmp_path / "outside.bin").resolve()))


def test_path_creates_only_requested_parent(tmp_path: Path) -> None:
    layout = StorageLayout(tmp_path / "storage")
    target = layout.path("benchmarks", "results", "run.json", create_parent=True)
    assert target.parent.is_dir()
    assert target.is_relative_to(layout.root)
