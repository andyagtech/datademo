"""
Storage and I/O adapters for local and cloud execution.

The StorageAdapter protocol defines the interface that pipeline steps
use for all file I/O. This allows the same step logic to run against
a local filesystem or AWS S3 without changes.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class StorageAdapter(Protocol):
    """Abstract file I/O interface used by pipeline steps."""

    def read_bytes(self, key: str) -> bytes:
        """Read a file and return its contents as bytes."""
        ...

    def write_bytes(self, key: str, data: bytes) -> str:
        """Write bytes to a file. Returns the canonical path/URI of the written file."""
        ...

    def read_text(self, key: str, encoding: str = "utf-8") -> str:
        """Read a file and return its contents as a string."""
        ...

    def write_text(self, key: str, data: str, encoding: str = "utf-8") -> str:
        """Write a string to a file. Returns the canonical path/URI."""
        ...

    def list_files(self, prefix: str, pattern: str = "*") -> list[str]:
        """List files under a prefix matching an optional glob pattern."""
        ...

    def file_exists(self, key: str) -> bool:
        """Check if a file exists."""
        ...

    def file_size(self, key: str) -> int:
        """Return file size in bytes."""
        ...

    def get_uri(self, key: str) -> str:
        """Return a canonical URI for DuckDB to read from (local path or s3:// URL)."""
        ...
