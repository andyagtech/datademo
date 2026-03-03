"""
Local filesystem storage adapter.

Maps keys to paths relative to a base directory.
DuckDB URIs are plain filesystem paths.
"""

from __future__ import annotations

import fnmatch
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class LocalStorage:
    """StorageAdapter implementation backed by the local filesystem."""

    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir.resolve()

    def _resolve(self, key: str) -> Path:
        """Resolve a key to an absolute path under base_dir."""
        return self.base_dir / key

    def read_bytes(self, key: str) -> bytes:
        return self._resolve(key).read_bytes()

    def write_bytes(self, key: str, data: bytes) -> str:
        path = self._resolve(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return str(path)

    def read_text(self, key: str, encoding: str = "utf-8") -> str:
        return self._resolve(key).read_text(encoding=encoding)

    def write_text(self, key: str, data: str, encoding: str = "utf-8") -> str:
        path = self._resolve(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(data, encoding=encoding)
        return str(path)

    def list_files(self, prefix: str, pattern: str = "*") -> list[str]:
        base = self._resolve(prefix)
        if not base.is_dir():
            return []
        results = []
        for p in sorted(base.rglob("*")):
            if p.is_file() and fnmatch.fnmatch(p.name, pattern):
                # Return key relative to base_dir
                results.append(str(p.relative_to(self.base_dir)))
        return results

    def file_exists(self, key: str) -> bool:
        return self._resolve(key).exists()

    def file_size(self, key: str) -> int:
        return self._resolve(key).stat().st_size

    def get_uri(self, key: str) -> str:
        """Return absolute filesystem path — DuckDB reads these natively."""
        return str(self._resolve(key))
