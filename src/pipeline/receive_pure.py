"""
Pure Functional File Operations for Step 1 (RECEIVE)

These functions use the Result type for explicit error handling
and avoid mutable state. They serve as the foundation for the
functional refactoring of the pipeline.
"""

from __future__ import annotations

import hashlib
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from src.functional import Result, Success, Failure, Maybe, Some, Nothing, try_op


@dataclass(frozen=True)
class FileInfo:
    """Immutable file metadata."""
    name: str
    path: str
    size_bytes: int
    sha256: str
    
    @property
    def size_mb(self) -> float:
        return round(self.size_bytes / (1024 * 1024), 1)
    
    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "size_bytes": self.size_bytes,
            "size_mb": self.size_mb,
            "sha256": self.sha256,
        }


@dataclass(frozen=True)
class FileInventory:
    """Immutable inventory of discovered files."""
    files: tuple[FileInfo, ...]
    
    def get(self, name: str) -> Maybe[FileInfo]:
        """Lookup file by name."""
        for f in self.files:
            if f.name == name:
                return Some(f)
        return Nothing()
    
    def filter_by_pattern(self, pattern: str) -> FileInventory:
        """Filter files by glob pattern."""
        from fnmatch import fnmatch
        return FileInventory(
            files=tuple(f for f in self.files if fnmatch(f.name, pattern))
        )
    
    def to_dict(self) -> dict[str, dict]:
        """Convert to dictionary for serialization."""
        return {f.name: f.to_dict() for f in self.files}


@dataclass(frozen=True)
class DiscoveredFiles:
    """Immutable discovery result by category."""
    beneficiary: tuple[str, ...]
    carrier_claims: tuple[str, ...]
    
    @property
    def all_files(self) -> tuple[str, ...]:
        return self.beneficiary + self.carrier_claims
    
    def to_dict(self) -> dict[str, list[str]]:
        return {
            "beneficiary": list(self.beneficiary),
            "carrier_claims": list(self.carrier_claims),
        }


@dataclass(frozen=True)
class ExtractResult:
    """Result of zip extraction."""
    extracted_paths: tuple[str, ...]
    dest_dir: str


@dataclass(frozen=True)
class ReceiveResult:
    """Complete receive step result."""
    source_dir: str
    discovered: DiscoveredFiles
    inventory: FileInventory
    missing_categories: tuple[str, ...]
    
    @property
    def is_complete(self) -> bool:
        return len(self.missing_categories) == 0
    
    def to_legacy_dict(self) -> dict:
        """Convert to legacy format for compatibility."""
        return {
            "source_dir": self.source_dir,
            "discovered": self.discovered.to_dict(),
            "files_found": list(self.discovered.all_files),
            "missing_categories": list(self.missing_categories),
            "inventory": self.inventory.to_dict(),
            "complete": self.is_complete,
        }


# Pure functions for file operations
def compute_sha256(path: Path) -> Result[str, Exception]:
    """
    Pure wrapper for SHA-256 computation.
    
    Returns Result with hash or exception.
    """
    def _compute() -> str:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()
    
    return try_op(_compute)


def inventory_directory(directory: Path) -> Result[FileInventory, Exception]:
    """
    Build immutable inventory of CSV files in directory.
    
    Returns Result with FileInventory or exception.
    """
    def _inventory() -> FileInventory:
        files = []
        for p in sorted(directory.glob("*.csv")):
            hash_result = compute_sha256(p)
            if hash_result.is_err:
                raise hash_result.unwrap()  # Will be caught by try_op wrapper
            
            files.append(FileInfo(
                name=p.name,
                path=str(p),
                size_bytes=p.stat().st_size,
                sha256=hash_result.unwrap()
            ))
        return FileInventory(files=tuple(files))
    
    return try_op(_inventory)


def discover_files(directory: Path) -> DiscoveredFiles:
    """
    Pure function: Discover CSV files by category.
    
    No side effects - only glob operations.
    """
    BENEFICIARY_PATTERN = "*Beneficiary*"
    CARRIER_PATTERN = "*Carrier*"
    
    beneficiary = tuple(
        f.name for f in directory.glob(BENEFICIARY_PATTERN)
        if f.suffix == ".csv"
    )
    carrier = tuple(
        f.name for f in directory.glob(CARRIER_PATTERN)
        if f.suffix == ".csv"
    )
    
    return DiscoveredFiles(
        beneficiary=tuple(sorted(beneficiary)),
        carrier_claims=tuple(sorted(carrier))
    )


def extract_zip(
    zip_path: Path,
    dest_dir: Path,
    password: str | None = None
) -> Result[ExtractResult, Exception]:
    """
    Extract zip file to destination directory.
    
    Returns Result with ExtractResult or exception.
    """
    def _extract() -> ExtractResult:
        dest_dir.mkdir(parents=True, exist_ok=True)
        pw_bytes = password.encode() if password else None
        
        extracted = []
        with zipfile.ZipFile(zip_path, "r") as zf:
            for info in zf.infolist():
                if info.is_dir():
                    continue
                zf.extract(info, dest_dir, pwd=pw_bytes)
                extracted.append(str(dest_dir / info.filename))
        
        return ExtractResult(
            extracted_paths=tuple(sorted(extracted)),
            dest_dir=str(dest_dir)
        )
    
    return try_op(_extract)


def validate_discovery(
    discovered: DiscoveredFiles,
    expected_beneficiary: int = 3,
    expected_carrier: int = 2
) -> tuple[bool, tuple[str, ...]]:
    """
    Pure validation: Check if discovery meets requirements.
    
    Returns (is_valid, missing_categories).
    """
    missing = []
    
    if len(discovered.beneficiary) < expected_beneficiary:
        missing.append(
            f"beneficiary: found {len(discovered.beneficiary)}, "
            f"need {expected_beneficiary}"
        )
    
    if len(discovered.carrier_claims) < expected_carrier:
        missing.append(
            f"carrier_claims: found {len(discovered.carrier_claims)}, "
            f"need {expected_carrier}"
        )
    
    return len(missing) == 0, tuple(missing)


# Higher-order functions for composition
def with_zip_extraction(
    directory: Path,
    password: str | None = None
) -> Callable[[Path], Result[Path, Exception]]:
    """
    Higher-order function: Creates function that extracts zips if needed.
    
    Returns a function that takes a directory and returns the directory
    (with zips extracted as side effect).
    """
    def processor(input_dir: Path) -> Result[Path, Exception]:
        zips = list(input_dir.glob("*.zip"))
        if not zips:
            return Success(input_dir)
        
        for zip_file in zips:
            result = extract_zip(zip_file, directory, password)
            if result.is_err:
                return Failure(result.unwrap())
        
        return Success(directory)
    
    return processor


# Pipeline composition for receive step
def receive_step_pure(
    data_dir: Path,
    old_system_subdir: str = "old_system",
    expected_beneficiary: int = 3,
    expected_carrier: int = 2
) -> Result[ReceiveResult, Exception]:
    """
    Pure functional receive step.
    
    Composes smaller pure functions into complete step.
    """
    old_system_dir = data_dir / old_system_subdir
    
    # Ensure directory exists (side effect isolated at boundary)
    if not old_system_dir.exists():
        old_system_dir.mkdir(parents=True, exist_ok=True)
    
    # Compose operations
    return (
        inventory_directory(old_system_dir)
        .bind(lambda inventory: 
            Success((inventory, discover_files(old_system_dir)))
        )
        .bind(lambda pair: 
            _create_receive_result(
                source_dir=str(old_system_dir),
                discovered=pair[1],
                inventory=pair[0],
                expected_beneficiary=expected_beneficiary,
                expected_carrier=expected_carrier
            )
        )
    )


def _create_receive_result(
    source_dir: str,
    discovered: DiscoveredFiles,
    inventory: FileInventory,
    expected_beneficiary: int,
    expected_carrier: int
) -> Result[ReceiveResult, Exception]:
    """Helper: Create ReceiveResult from validated inputs."""
    is_complete, missing = validate_discovery(
        discovered,
        expected_beneficiary=expected_beneficiary,
        expected_carrier=expected_carrier
    )
    
    # Even if incomplete, we return the result - caller decides on failure
    return Success(ReceiveResult(
        source_dir=source_dir,
        discovered=discovered,
        inventory=inventory,
        missing_categories=missing
    ))


__all__ = [
    "FileInfo",
    "FileInventory",
    "DiscoveredFiles",
    "ExtractResult",
    "ReceiveResult",
    "compute_sha256",
    "inventory_directory",
    "discover_files",
    "extract_zip",
    "validate_discovery",
    "receive_step_pure",
]
