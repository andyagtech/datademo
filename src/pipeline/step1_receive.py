"""
STEP 1: RECEIVE — Accept files, verify integrity, extract zips.

Responsibilities:
  - Accept a zip or directory of CSVs
  - Extract zips (with optional password)
  - Verify all expected files are present
  - Compute SHA-256 checksums for audit trail
  - Report file sizes for sanity checks
"""

import hashlib
import logging
import shutil
import zipfile
from pathlib import Path

from src.pipeline import PipelineContext, StepResult

logger = logging.getLogger(__name__)

EXPECTED_OLD_FILES = {
    "beneficiary": [
        "DE1_0_2008_Beneficiary_Summary_File_Sample_1.csv",
        "DE1_0_2009_Beneficiary_Summary_File_Sample_1.csv",
        "DE1_0_2010_Beneficiary_Summary_File_Sample_1.csv",
    ],
    "carrier_claims": [
        "DE1_0_2008_to_2010_Carrier_Claims_Sample_1A.csv",
        "DE1_0_2008_to_2010_Carrier_Claims_Sample_1B.csv",
    ],
}

# New system files can have flexible names — we match by pattern
NEW_FILE_PATTERNS = {
    "beneficiary": "*Beneficiary*",
    "carrier_claims": "*Carrier*",
}


def _sha256(path: Path) -> str:
    """Compute SHA-256 hash of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _extract_zip(zip_path: Path, dest_dir: Path, password: str | None = None) -> list[Path]:
    """Extract a zip file and return list of extracted paths."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    pw_bytes = password.encode() if password else None

    extracted = []
    with zipfile.ZipFile(zip_path, "r") as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            zf.extract(info, dest_dir, pwd=pw_bytes)
            extracted.append(dest_dir / info.filename)

    return extracted


def _inventory_files(directory: Path) -> dict:
    """Build an inventory of CSV files with sizes and checksums."""
    inventory = {}
    for p in sorted(directory.glob("*.csv")):
        inventory[p.name] = {
            "path": str(p),
            "size_bytes": p.stat().st_size,
            "size_mb": round(p.stat().st_size / (1024 * 1024), 1),
            "sha256": _sha256(p),
        }
    return inventory


def _check_expected_files(directory: Path, expected: dict[str, list[str]]) -> tuple[list[str], list[str]]:
    """Check which expected files are present/missing."""
    found = []
    missing = []
    for category, filenames in expected.items():
        for fn in filenames:
            if (directory / fn).exists():
                found.append(fn)
            else:
                missing.append(fn)
    return found, missing


def receive_old_system(ctx: PipelineContext) -> dict:
    """Validate the old system data directory."""
    data_dir = ctx.old_data_dir

    # Check for zips that need extraction
    zips = list(data_dir.glob("*.zip"))
    raw_dir = data_dir / "raw" if (data_dir / "raw").exists() else data_dir

    # If CSVs are in a raw/ subdirectory, use that
    csv_files = list(raw_dir.glob("*.csv"))
    if not csv_files and zips:
        logger.info(f"Found {len(zips)} zip files, extracting...")
        raw_dir = data_dir / "raw"
        for z in zips:
            _extract_zip(z, raw_dir)
        csv_files = list(raw_dir.glob("*.csv"))

    found, missing = _check_expected_files(raw_dir, EXPECTED_OLD_FILES)
    inventory = _inventory_files(raw_dir)

    return {
        "source_dir": str(raw_dir),
        "files_found": found,
        "files_missing": missing,
        "inventory": inventory,
        "complete": len(missing) == 0,
    }


def receive_new_system(ctx: PipelineContext) -> dict | None:
    """Validate the new system data directory or zip."""
    if not ctx.new_data_dir:
        return None

    new_dir = ctx.new_data_dir

    # Handle zip file input
    if new_dir.is_file() and new_dir.suffix == ".zip":
        extract_dir = new_dir.parent / "new_system_extracted"
        logger.info(f"Extracting new system zip: {new_dir}")
        _extract_zip(new_dir, extract_dir)
        new_dir = extract_dir

    if not new_dir.is_dir():
        return {"error": f"New data path does not exist: {new_dir}"}

    # Find files by pattern
    found_files = {}
    for category, pattern in NEW_FILE_PATTERNS.items():
        matches = sorted(new_dir.glob(pattern))
        # Also check for .csv extension explicitly
        if not matches:
            matches = sorted(new_dir.glob(f"{pattern}.csv"))
        found_files[category] = [str(m) for m in matches]

    inventory = _inventory_files(new_dir)

    has_beneficiary = len(found_files.get("beneficiary", [])) > 0
    has_claims = len(found_files.get("carrier_claims", [])) > 0

    return {
        "source_dir": str(new_dir),
        "found_files": found_files,
        "inventory": inventory,
        "has_beneficiary": has_beneficiary,
        "has_claims": has_claims,
        "complete": has_beneficiary and has_claims,
    }


def run(ctx: PipelineContext) -> StepResult:
    """Execute Step 1: Receive and verify files."""
    errors = []
    warnings = []

    # Old system
    old_result = receive_old_system(ctx)
    if not old_result["complete"]:
        errors.append(f"Missing old system files: {old_result['files_missing']}")

    # New system (optional)
    new_result = receive_new_system(ctx)
    if new_result and "error" in new_result:
        errors.append(new_result["error"])
    elif new_result and not new_result["complete"]:
        warnings.append(
            f"New system data incomplete: beneficiary={new_result['has_beneficiary']}, "
            f"claims={new_result['has_claims']}"
        )

    # Store in context
    ctx.results["receive"] = {
        "old_system": old_result,
        "new_system": new_result,
    }

    success = len(errors) == 0
    if not success:
        ctx.halted = True
        ctx.halt_reason = "; ".join(errors)

    total_files = len(old_result.get("inventory", {}))
    if new_result and "inventory" in new_result:
        total_files += len(new_result["inventory"])

    return StepResult(
        step_name="receive",
        success=success,
        message=f"Received {total_files} CSV files",
        data=ctx.results["receive"],
        errors=errors,
        warnings=warnings,
    )
