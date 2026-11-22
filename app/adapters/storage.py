"""Pluggable file storage adapter interface and local filesystem implementation."""

import re
from abc import ABC, abstractmethod
from pathlib import Path, PurePosixPath

_SAFE_SEGMENT_RE = re.compile(r"^[A-Za-z0-9._-]+$")


def sanitize_storage_key(file_key: str) -> PurePosixPath:
    """Validate and normalize a relative storage key to prevent path traversal."""
    if not file_key or "\x00" in file_key or "\\" in file_key:
        raise ValueError("Invalid storage key.")

    normalized = PurePosixPath(file_key)
    if normalized.is_absolute() or not normalized.parts:
        raise ValueError("Storage key must be a non-empty relative path.")

    for part in normalized.parts:
        if part in {".", ".."} or not _SAFE_SEGMENT_RE.match(part):
            raise ValueError(f"Unsafe storage key segment: {part!r}")

    return normalized


class StorageAdapter(ABC):
    """Abstract interface for storing, reading, and deleting versioned manuscript files."""

    @abstractmethod
    def save_file(self, file_key: str, data: bytes) -> str:
        """Persist raw bytes under the given key and return the canonical key."""

    @abstractmethod
    def read_file(self, file_key: str) -> bytes:
        """Read and return raw bytes for the given key, raising FileNotFoundError if absent."""

    @abstractmethod
    def delete_file(self, file_key: str) -> None:
        """Delete the stored file for the given key if it exists."""


class LocalFilesystemStorageAdapter(StorageAdapter):
    """Zero-cost local filesystem implementation of StorageAdapter."""

    def __init__(self, base_dir: Path | str) -> None:
        self.base_dir = Path(base_dir).resolve()

    def _resolve_target(self, file_key: str) -> tuple[str, Path]:
        rel_path = sanitize_storage_key(file_key)
        target = (self.base_dir / Path(*rel_path.parts)).resolve()
        if not target.is_relative_to(self.base_dir):
            raise ValueError("Resolved storage path escapes the configured base directory.")
        return rel_path.as_posix(), target

    def save_file(self, file_key: str, data: bytes) -> str:
        canonical_key, target = self._resolve_target(file_key)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return canonical_key

    def read_file(self, file_key: str) -> bytes:
        _, target = self._resolve_target(file_key)
        if not target.is_file():
            raise FileNotFoundError(f"Stored file not found for key '{file_key}'.")
        return target.read_bytes()

    def delete_file(self, file_key: str) -> None:
        _, target = self._resolve_target(file_key)
        target.unlink(missing_ok=True)
