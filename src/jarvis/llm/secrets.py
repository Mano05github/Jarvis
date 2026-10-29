"""Secret-store abstractions and a Windows user-bound DPAPI implementation."""

from __future__ import annotations

import ctypes
import hashlib
import os
from ctypes import wintypes
from pathlib import Path
from typing import Protocol


class SecretStore(Protocol):
    def get(self, reference: str) -> str | None: ...

    def put(self, reference: str, secret: str) -> None: ...

    def contains(self, reference: str) -> bool: ...


class InMemorySecretStore:
    """Non-persistent store for tests; never use it for production credentials."""

    def __init__(self) -> None:
        self._values: dict[str, str] = {}

    def get(self, reference: str) -> str | None:
        return self._values.get(reference)

    def put(self, reference: str, secret: str) -> None:
        if not reference.strip() or not secret:
            raise ValueError("secret reference and value must be non-empty")
        self._values[reference] = secret

    def contains(self, reference: str) -> bool:
        return reference in self._values


class _DataBlob(ctypes.Structure):
    _fields_ = [
        ("cbData", wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_ubyte)),
    ]


def _input_blob(payload: bytes) -> tuple[_DataBlob, ctypes.Array[ctypes.c_char]]:
    buffer = ctypes.create_string_buffer(payload)
    pointer = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte))
    return _DataBlob(len(payload), pointer), buffer


class DPAPISecretStore:
    """Persist secrets encrypted for the current Windows user with no plaintext index."""

    _UI_FORBIDDEN = 0x1

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def _target(self, reference: str) -> Path:
        if not reference.strip():
            raise ValueError("secret reference must be non-empty")
        digest = hashlib.sha256(reference.encode("utf-8")).hexdigest()
        return self.root / f"{digest}.dpapi"

    @staticmethod
    def _libraries() -> tuple[ctypes.WinDLL, ctypes.WinDLL]:
        if os.name != "nt":
            raise OSError("DPAPI secret storage is available only on Windows")
        return ctypes.WinDLL("crypt32", use_last_error=True), ctypes.WinDLL(
            "kernel32", use_last_error=True
        )

    @classmethod
    def _protect(cls, payload: bytes) -> bytes:
        crypt32, kernel32 = cls._libraries()
        source, source_buffer = _input_blob(payload)
        output = _DataBlob()
        crypt32.CryptProtectData.restype = wintypes.BOOL
        succeeded = crypt32.CryptProtectData(
            ctypes.byref(source),
            None,
            None,
            None,
            None,
            cls._UI_FORBIDDEN,
            ctypes.byref(output),
        )
        if not succeeded:
            raise ctypes.WinError(ctypes.get_last_error())
        del source_buffer
        try:
            return ctypes.string_at(output.pbData, output.cbData)
        finally:
            kernel32.LocalFree(output.pbData)

    @classmethod
    def _unprotect(cls, payload: bytes) -> bytes:
        crypt32, kernel32 = cls._libraries()
        source, source_buffer = _input_blob(payload)
        output = _DataBlob()
        crypt32.CryptUnprotectData.restype = wintypes.BOOL
        succeeded = crypt32.CryptUnprotectData(
            ctypes.byref(source),
            None,
            None,
            None,
            None,
            cls._UI_FORBIDDEN,
            ctypes.byref(output),
        )
        if not succeeded:
            raise ctypes.WinError(ctypes.get_last_error())
        del source_buffer
        try:
            return ctypes.string_at(output.pbData, output.cbData)
        finally:
            kernel32.LocalFree(output.pbData)

    def get(self, reference: str) -> str | None:
        target = self._target(reference)
        if not target.is_file():
            return None
        return self._unprotect(target.read_bytes()).decode("utf-8")

    def put(self, reference: str, secret: str) -> None:
        if not secret:
            raise ValueError("secret value must be non-empty")
        target = self._target(reference)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(".partial")
        temporary.write_bytes(self._protect(secret.encode("utf-8")))
        os.replace(temporary, target)

    def contains(self, reference: str) -> bool:
        return self._target(reference).is_file()


__all__ = ["DPAPISecretStore", "InMemorySecretStore", "SecretStore"]
