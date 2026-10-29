"""Privacy-safe system inventory used by Phase 1 benchmarks."""

from __future__ import annotations

import os
import platform
import sys
from typing import Any

import psutil  # type: ignore[import-untyped]

from jarvis.storage import StorageLayout


def system_inventory(layout: StorageLayout) -> dict[str, Any]:
    memory = psutil.virtual_memory()
    disk = psutil.disk_usage(str(layout.root))
    return {
        "python": {
            "version": platform.python_version(),
            "executable": sys.executable,
            "implementation": platform.python_implementation(),
        },
        "system": {
            "platform": platform.platform(),
            "machine": platform.machine(),
            "processor": platform.processor(),
            "logical_cpu_count": psutil.cpu_count(logical=True),
            "physical_cpu_count": psutil.cpu_count(logical=False),
        },
        "memory": {"total_bytes": memory.total, "available_bytes": memory.available},
        "storage": {
            "root": str(layout.root),
            "total_bytes": disk.total,
            "free_bytes": disk.free,
        },
        "environment": {
            name: os.environ.get(name)
            for name in (
                "JARVIS_STORAGE_ROOT",
                "JARVIS_ENGINE_ROOT",
                "HF_HOME",
                "TORCH_HOME",
                "PIP_CACHE_DIR",
                "UV_CACHE_DIR",
                "TMP",
                "TEMP",
            )
        },
    }
