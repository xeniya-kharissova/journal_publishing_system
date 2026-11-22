"""Pluggable external infrastructure adapters (storage, email, plagiarism, ORCID)."""

from app.adapters.storage import (
    LocalFilesystemStorageAdapter,
    StorageAdapter,
    sanitize_storage_key,
)

__all__ = [
    "LocalFilesystemStorageAdapter",
    "StorageAdapter",
    "sanitize_storage_key",
]
