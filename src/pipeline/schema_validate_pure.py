"""
Pure Functional Schema Validation for Step 2 (SCHEMA VALIDATE)

All validation logic is pure — no mutable state, no PipelineContext.
Functions return Result/immutable dataclasses for explicit error handling.
"""

from __future__ import annotations

import csv
import logging
from dataclasses import dataclass
from pathlib import Path

from src.functional import Result, Success, Failure, try_op, is_err

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Expected column schemas (from CMS DE-SynPUF codebook)
# ---------------------------------------------------------------------------

BENEFICIARY_EXPECTED_COLS: frozenset[str] = frozenset({
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
})

CARRIER_EXPECTED_COLS: frozenset[str] = frozenset({
    "DESYNPUF_ID", "CLM_ID", "CLM_FROM_DT", "CLM_THRU_DT",
    "ICD9_DGNS_CD_1", "ICD9_DGNS_CD_2", "ICD9_DGNS_CD_3", "ICD9_DGNS_CD_4",
    "ICD9_DGNS_CD_5", "ICD9_DGNS_CD_6", "ICD9_DGNS_CD_7", "ICD9_DGNS_CD_8",
    "LINE_NCH_PMT_AMT_1", "LINE_BENE_PTB_DDCTBL_AMT_1",
    "LINE_BENE_PRMRY_PYR_PD_AMT_1", "LINE_COINSRNC_AMT_1",
    "LINE_ALOWD_CHRG_AMT_1", "LINE_PRCSG_IND_CD_1",
    "HCPCS_CD_1",
})


# ---------------------------------------------------------------------------
# Immutable result types
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class FileType:
    """Algebraic type for file classification."""
    kind: str  # "beneficiary" | "carrier_claims" | "unknown"

    @property
    def is_known(self) -> bool:
        return self.kind in ("beneficiary", "carrier_claims")


@dataclass(frozen=True)
class ColumnDiff:
    """Immutable diff between actual and expected columns."""
    missing: tuple[str, ...]
    extra: tuple[str, ...]

    @property
    def has_missing(self) -> bool:
        return len(self.missing) > 0


@dataclass(frozen=True)
class FileValidation:
    """Immutable validation result for a single CSV file."""
    file_name: str
    path: str
    valid: bool
    file_type: FileType
    headers: tuple[str, ...]
    column_diff: ColumnDiff
    errors: tuple[str, ...]
    warnings: tuple[str, ...]
    sample_rows: tuple[dict, ...]

    def to_legacy_dict(self) -> dict:
        """Convert to legacy dict format for compatibility."""
        return {
            "file": self.file_name,
            "path": self.path,
            "valid": self.valid,
            "file_type": self.file_type.kind if self.file_type.is_known else None,
            "headers": list(self.headers),
            "header_count": len(self.headers),
            "missing_columns": list(self.column_diff.missing),
            "extra_columns": list(self.column_diff.extra),
            "warnings": list(self.warnings),
            "errors": list(self.errors),
            "sample_rows": list(self.sample_rows),
        }


@dataclass(frozen=True)
class SchemaValidationResult:
    """Immutable result for the entire schema validation step."""
    validations: tuple[FileValidation, ...]

    @property
    def valid_count(self) -> int:
        return sum(1 for v in self.validations if v.valid)

    @property
    def total_count(self) -> int:
        return len(self.validations)

    @property
    def all_valid(self) -> bool:
        return all(v.valid for v in self.validations)

    @property
    def beneficiary_files(self) -> tuple[FileValidation, ...]:
        return tuple(v for v in self.validations if v.file_type.kind == "beneficiary")

    @property
    def carrier_files(self) -> tuple[FileValidation, ...]:
        return tuple(v for v in self.validations if v.file_type.kind == "carrier_claims")

    @property
    def unknown_files(self) -> tuple[FileValidation, ...]:
        return tuple(v for v in self.validations if not v.file_type.is_known)

    @property
    def all_errors(self) -> tuple[str, ...]:
        return tuple(e for v in self.validations for e in v.errors)

    @property
    def all_warnings(self) -> tuple[str, ...]:
        return tuple(w for v in self.validations for w in v.warnings)

    def to_legacy_dict(self) -> dict:
        return {
            "file_validations": [v.to_legacy_dict() for v in self.validations],
            "valid_count": self.valid_count,
            "total_count": self.total_count,
            "beneficiary_files": len(self.beneficiary_files),
            "carrier_files": len(self.carrier_files),
            "unknown_files": len(self.unknown_files),
        }


# ---------------------------------------------------------------------------
# Pure functions
# ---------------------------------------------------------------------------

def read_csv_headers(path: Path) -> Result[tuple[str, ...], Exception]:
    """Pure: Read headers from a CSV file, returning Result."""
    def _read() -> tuple[str, ...]:
        with open(path, "r", newline="", encoding="utf-8-sig") as f:
            reader = csv.reader(f)
            headers = next(reader, [])
        return tuple(headers)
    return try_op(_read)


def check_encoding(path: Path) -> Result[None, str]:
    """Pure: Verify UTF-8 encoding. Returns Failure(error_msg) on bad encoding."""
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            f.read(1024)
        return Success(None)
    except UnicodeDecodeError as e:
        return Failure(f"Encoding error in {path.name}: {e}")


def classify_file(headers: tuple[str, ...]) -> FileType:
    """Pure: Classify a file based on its headers."""
    header_set = frozenset(headers)
    bene_overlap = len(header_set & BENEFICIARY_EXPECTED_COLS)
    carrier_overlap = len(header_set & CARRIER_EXPECTED_COLS)

    match (bene_overlap >= 20, carrier_overlap >= 10):
        case (True, _):
            return FileType(kind="beneficiary")
        case (_, True):
            return FileType(kind="carrier_claims")
        case _:
            return FileType(kind="unknown")


def compute_column_diff(headers: tuple[str, ...], file_type: FileType) -> ColumnDiff:
    """Pure: Compute missing/extra columns against expected schema."""
    header_set = frozenset(headers)

    match file_type.kind:
        case "beneficiary":
            expected = BENEFICIARY_EXPECTED_COLS
        case "carrier_claims":
            expected = CARRIER_EXPECTED_COLS
        case _:
            return ColumnDiff(missing=(), extra=())

    return ColumnDiff(
        missing=tuple(sorted(expected - header_set)),
        extra=tuple(sorted(header_set - expected)),
    )


def sample_csv_rows(path: Path, n: int = 3) -> Result[tuple[dict, ...], Exception]:
    """Pure: Read first n data rows from a CSV."""
    def _read() -> tuple[dict, ...]:
        with open(path, "r", newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            rows: list[dict] = []
            for i, row in enumerate(reader):
                if i >= n:
                    break
                rows.append(row)
        return tuple(rows)
    return try_op(_read)


def validate_file_pure(path: Path) -> FileValidation:
    """
    Pure: Validate a single CSV file's schema.

    Composes read_csv_headers, classify_file, compute_column_diff, sample_csv_rows
    into a single immutable FileValidation result.
    """
    errors: list[str] = []
    warnings: list[str] = []

    # Check encoding
    enc_result = check_encoding(path)
    if is_err(enc_result):
        return FileValidation(
            file_name=path.name, path=str(path), valid=False,
            file_type=FileType(kind="unknown"), headers=(),
            column_diff=ColumnDiff(missing=(), extra=()),
            errors=(enc_result.failure(),), warnings=(), sample_rows=(),
        )

    # Read headers
    header_result = read_csv_headers(path)
    if is_err(header_result):
        return FileValidation(
            file_name=path.name, path=str(path), valid=False,
            file_type=FileType(kind="unknown"), headers=(),
            column_diff=ColumnDiff(missing=(), extra=()),
            errors=(f"Could not read headers: {header_result.failure()}",),
            warnings=(), sample_rows=(),
        )

    headers = header_result.unwrap()
    if not headers:
        return FileValidation(
            file_name=path.name, path=str(path), valid=False,
            file_type=FileType(kind="unknown"), headers=(),
            column_diff=ColumnDiff(missing=(), extra=()),
            errors=(f"No headers found in {path.name}",),
            warnings=(), sample_rows=(),
        )

    # Classify → diff → sample (pure pipeline)
    file_type = classify_file(headers)
    column_diff = compute_column_diff(headers, file_type)

    if not file_type.is_known:
        warnings.append(
            f"Could not classify {path.name} — headers don't match known schemas"
        )
    if column_diff.has_missing:
        warnings.append(f"Missing expected columns: {list(column_diff.missing)}")

    sample_result = sample_csv_rows(path)
    samples = sample_result.value_or(())
    if is_err(sample_result):
        warnings.append(f"Could not sample rows: {sample_result.failure()}")

    return FileValidation(
        file_name=path.name,
        path=str(path),
        valid=len(errors) == 0,
        file_type=file_type,
        headers=headers,
        column_diff=column_diff,
        errors=tuple(errors),
        warnings=tuple(warnings),
        sample_rows=samples,
    )


def validate_directory(directory: Path) -> Result[tuple[FileValidation, ...], Exception]:
    """Pure: Validate all CSV files in a directory."""
    def _validate() -> tuple[FileValidation, ...]:
        return tuple(
            validate_file_pure(p) for p in sorted(directory.glob("*.csv"))
        )
    return try_op(_validate)


def schema_validate_pure(
    old_system_dir: Path,
    new_system_dir: Path | None = None,
) -> Result[SchemaValidationResult, Exception]:
    """
    Pure functional schema validation step.

    Composes validate_directory for old + new system directories
    into a single SchemaValidationResult.
    """
    def _validate() -> SchemaValidationResult:
        old_result = validate_directory(old_system_dir)
        if is_err(old_result):
            raise old_result.failure()

        validations = list(old_result.unwrap())

        if new_system_dir and new_system_dir.is_dir():
            new_result = validate_directory(new_system_dir)
            if is_err(new_result):
                raise new_result.failure()
            validations.extend(new_result.unwrap())

        return SchemaValidationResult(validations=tuple(validations))

    return try_op(_validate)


__all__ = [
    "FileType",
    "ColumnDiff",
    "FileValidation",
    "SchemaValidationResult",
    "BENEFICIARY_EXPECTED_COLS",
    "CARRIER_EXPECTED_COLS",
    "read_csv_headers",
    "check_encoding",
    "classify_file",
    "compute_column_diff",
    "sample_csv_rows",
    "validate_file_pure",
    "validate_directory",
    "schema_validate_pure",
]
