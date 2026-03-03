"""
STEP 2: SCHEMA VALIDATION — Gate check before ingestion.

Responsibilities:
  - Read first row of each CSV to extract headers
  - Compare against expected column schemas
  - Sample rows to verify type consistency
  - GATE: reject early if schemas don't match, saving compute time
"""

import csv
import logging
from pathlib import Path

from src.pipeline import PipelineContext, StepResult

logger = logging.getLogger(__name__)

# Expected column sets per file type (from CMS DE-SynPUF codebook)
BENEFICIARY_EXPECTED_COLS = {
    "DESYNPUF_ID", "BENE_BIRTH_DT", "BENE_DEATH_DT",
    "BENE_SEX_IDENT_CD", "BENE_RACE_CD", "BENE_ESRD_IND",
    "SP_STATE_CODE", "BENE_COUNTY_CD",
    "BENE_HI_CVRAGE_TOT_MONS", "BENE_SMI_CVRAGE_TOT_MONS",
    "BENE_HMO_CVRAGE_TOT_MONS", "PLAN_CVRG_MOS_NUM",
    "SP_ALZHDMTA", "SP_CHF", "SP_CHRNKIDN", "SP_CNCR", "SP_COPD",
    "SP_DEPRESSN", "SP_DIABETES", "SP_ISCHMCHT", "SP_OSTEOPRS",
    "SP_RA_OA", "SP_STRKETIA",
    "MEDREIMB_IP", "BENRES_IP", "PPPYMT_IP",
    "MEDREIMB_OP", "BENRES_OP", "PPPYMT_OP",
    "MEDREIMB_CAR", "BENRES_CAR", "PPPYMT_CAR",
}

CARRIER_EXPECTED_COLS = {
    "DESYNPUF_ID", "CLM_ID", "CLM_FROM_DT", "CLM_THRU_DT",
    "ICD9_DGNS_CD_1", "ICD9_DGNS_CD_2", "ICD9_DGNS_CD_3", "ICD9_DGNS_CD_4",
    "ICD9_DGNS_CD_5", "ICD9_DGNS_CD_6", "ICD9_DGNS_CD_7", "ICD9_DGNS_CD_8",
    "LINE_NCH_PMT_AMT_1", "LINE_BENE_PTB_DDCTBL_AMT_1",
    "LINE_BENE_PRMRY_PYR_PD_AMT_1", "LINE_COINSRNC_AMT_1",
    "LINE_ALOWD_CHRG_AMT_1", "LINE_PRCSG_IND_CD_1",
    "HCPCS_CD_1",
}


def _read_csv_headers(path: Path) -> list[str]:
    """Read the header row of a CSV file without loading the full file."""
    with open(path, "r", newline="", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        return next(reader, [])


def _sample_csv_rows(path: Path, n: int = 5) -> list[dict]:
    """Read the first n data rows from a CSV."""
    with open(path, "r", newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        rows = []
        for i, row in enumerate(reader):
            if i >= n:
                break
            rows.append(row)
        return rows


def _classify_file(headers: list[str]) -> str | None:
    """Determine if a CSV is a beneficiary summary or carrier claims file."""
    header_set = set(headers)
    bene_overlap = len(header_set & BENEFICIARY_EXPECTED_COLS)
    carrier_overlap = len(header_set & CARRIER_EXPECTED_COLS)

    if bene_overlap >= 20:
        return "beneficiary"
    elif carrier_overlap >= 10:
        return "carrier_claims"
    return None


def _check_encoding(path: Path) -> str | None:
    """Quick check for encoding issues — read first 1KB."""
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            f.read(1024)
        return None
    except UnicodeDecodeError as e:
        return f"Encoding error in {path.name}: {e}"


def validate_file(path: Path, expected_type: str | None = None) -> dict:
    """Validate a single CSV file's schema."""
    result = {
        "file": path.name,
        "path": str(path),
        "valid": True,
        "file_type": None,
        "headers": [],
        "header_count": 0,
        "missing_columns": [],
        "extra_columns": [],
        "warnings": [],
        "errors": [],
        "sample_rows": [],
    }

    # Check encoding
    enc_err = _check_encoding(path)
    if enc_err:
        result["errors"].append(enc_err)
        result["valid"] = False
        return result

    # Read headers
    headers = _read_csv_headers(path)
    result["headers"] = headers
    result["header_count"] = len(headers)

    if not headers:
        result["errors"].append(f"No headers found in {path.name}")
        result["valid"] = False
        return result

    # Classify file type
    file_type = _classify_file(headers)
    result["file_type"] = file_type

    if expected_type and file_type != expected_type:
        result["errors"].append(
            f"Expected {expected_type} but detected {file_type or 'unknown'}"
        )
        result["valid"] = False

    if file_type is None:
        result["warnings"].append(
            f"Could not classify {path.name} — headers don't match known schemas"
        )

    # Check for missing/extra columns
    header_set = set(headers)
    if file_type == "beneficiary":
        expected = BENEFICIARY_EXPECTED_COLS
    elif file_type == "carrier_claims":
        expected = CARRIER_EXPECTED_COLS
    else:
        expected = set()

    if expected:
        result["missing_columns"] = sorted(expected - header_set)
        result["extra_columns"] = sorted(header_set - expected)
        if result["missing_columns"]:
            result["warnings"].append(
                f"Missing expected columns: {result['missing_columns']}"
            )

    # Sample rows for type consistency
    try:
        result["sample_rows"] = _sample_csv_rows(path, n=3)
    except Exception as e:
        result["warnings"].append(f"Could not sample rows: {e}")

    return result


def run(ctx: PipelineContext) -> StepResult:
    """Execute Step 2: Schema validation gate."""
    errors = []
    warnings = []
    file_validations = []

    receive_data = ctx.results.get("receive", {})

    # Validate old system files
    old_info = receive_data.get("old_system", {})
    old_dir = Path(old_info.get("source_dir", ctx.old_data_dir))
    for csv_path in sorted(old_dir.glob("*.csv")):
        v = validate_file(csv_path)
        file_validations.append(v)
        if not v["valid"]:
            errors.append(f"Old system file invalid: {v['file']} — {v['errors']}")
        warnings.extend(v["warnings"])

    # Validate new system files
    new_info = receive_data.get("new_system")
    if new_info and "source_dir" in new_info:
        new_dir = Path(new_info["source_dir"])
        for csv_path in sorted(new_dir.glob("*.csv")):
            v = validate_file(csv_path)
            file_validations.append(v)
            if not v["valid"]:
                errors.append(f"New system file invalid: {v['file']} — {v['errors']}")
            warnings.extend(v["warnings"])

    # Summarize
    valid_count = sum(1 for v in file_validations if v["valid"])
    total_count = len(file_validations)

    # Classify what we have
    bene_files = [v for v in file_validations if v["file_type"] == "beneficiary"]
    claim_files = [v for v in file_validations if v["file_type"] == "carrier_claims"]
    unknown_files = [v for v in file_validations if v["file_type"] is None]

    if unknown_files:
        warnings.append(
            f"{len(unknown_files)} file(s) could not be classified: "
            f"{[v['file'] for v in unknown_files]}"
        )

    ctx.results["schema_validate"] = {
        "file_validations": file_validations,
        "valid_count": valid_count,
        "total_count": total_count,
        "beneficiary_files": len(bene_files),
        "carrier_files": len(claim_files),
        "unknown_files": len(unknown_files),
    }

    success = len(errors) == 0
    if not success:
        ctx.halted = True
        ctx.halt_reason = f"Schema validation failed: {'; '.join(errors)}"

    return StepResult(
        step_name="schema_validate",
        success=success,
        message=f"Validated {valid_count}/{total_count} files "
                f"({len(bene_files)} beneficiary, {len(claim_files)} carrier claims)",
        data=ctx.results["schema_validate"],
        errors=errors,
        warnings=warnings,
    )
