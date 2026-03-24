"""
Query Algebra — Pure Descriptions of Database Operations

Each operation is an immutable dataclass (the "what").
The interpreter module executes them against DuckDB (the "how").

This is the Interpreter Pattern / Free Monad approach:
  - Build a program as data (pure, testable, composable)
  - Run it with an interpreter (effectful, at the boundary)
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


# ---------------------------------------------------------------------------
# Ingest operations
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class IngestOp:
    """Description of a CSV → DuckDB table load."""
    source_path: Path
    target_table: str
    year_column: int | None = None  # If set, adds a summary_year column


@dataclass(frozen=True)
class IngestPlan:
    """Immutable plan for the entire ingest step."""
    operations: tuple[IngestOp, ...]
    skip_ingest: bool = False
    db_path: Path | None = None

    @property
    def table_names(self) -> tuple[str, ...]:
        return tuple(sorted({op.target_table for op in self.operations}))


# ---------------------------------------------------------------------------
# Anomaly check descriptions
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class AnomalyCheck:
    """Description of an anomaly detection query."""
    name: str
    table: str
    query: str  # SQL that returns COUNT(*) of anomalous rows
    severity: str  # "high" | "medium" | "low"
    column: str = ""


@dataclass(frozen=True)
class AnomalyResult:
    """Immutable result of an anomaly check."""
    check: AnomalyCheck
    count: int

    @property
    def is_anomalous(self) -> bool:
        return self.count > 0

    def to_dict(self) -> dict:
        return {
            "type": self.check.name,
            "table": self.check.table,
            "column": self.check.column,
            "count": self.count,
            "severity": self.check.severity,
        }


# ---------------------------------------------------------------------------
# Validation rule descriptions
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ValidationRule:
    """
    Declarative validation check — pure data, no execution.

    Each rule is a SQL query that counts violations.
    The interpreter runs the query and produces a ValidationOutcome.
    """
    name: str
    category: str  # identity, temporal, demographic, financial, clinical, coverage
    description: str
    count_query: str       # SQL returning (total_checked, issues_found)
    severity: str = "error"


@dataclass(frozen=True)
class ValidationOutcome:
    """Immutable result of executing a ValidationRule."""
    rule: ValidationRule
    total_checked: int
    issues_found: int

    @property
    def passed(self) -> bool:
        return self.issues_found == 0

    @property
    def issue_pct(self) -> float:
        return round(100.0 * self.issues_found / max(self.total_checked, 1), 4)

    def to_dict(self) -> dict:
        return {
            "check_name": self.rule.name,
            "category": self.rule.category,
            "description": self.rule.description,
            "total_checked": self.total_checked,
            "issues_found": self.issues_found,
            "issue_pct": self.issue_pct,
            "passed": self.passed,
        }


# ---------------------------------------------------------------------------
# Match / comparison operations (using Z-set algebra)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class MatchConfig:
    """Pure description of a table matching operation."""
    old_table: str
    new_table: str
    key_cols: tuple[str, ...]
    compare_cols: tuple[str, ...] = ()
    numeric_cols: tuple[str, ...] = ()
    zset_table: str = ""  # output Z-set table name

    def with_zset_table(self, name: str) -> MatchConfig:
        return MatchConfig(
            old_table=self.old_table,
            new_table=self.new_table,
            key_cols=self.key_cols,
            compare_cols=self.compare_cols,
            numeric_cols=self.numeric_cols,
            zset_table=name,
        )


# ---------------------------------------------------------------------------
# Report operations
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ExportOp:
    """Description of a table export to CSV/Parquet."""
    table_name: str
    csv_path: Path
    parquet_path: Path


@dataclass(frozen=True)
class ReportPlan:
    """Immutable plan for report generation."""
    report_dir: Path
    export_ops: tuple[ExportOp, ...]


# ---------------------------------------------------------------------------
# Predefined domain rules
# ---------------------------------------------------------------------------

# Anomaly checks for Step 3 (Ingest & Profile)
ANOMALY_CHECKS: tuple[AnomalyCheck, ...] = (
    *(
        AnomalyCheck(
            name="negative_payment",
            table="beneficiary_summary",
            query=f"SELECT COUNT(*) FROM beneficiary_summary WHERE {col} < 0",
            severity="high",
            column=col,
        )
        for col in [
            "MEDREIMB_CAR", "BENRES_CAR", "PPPYMT_CAR",
            "MEDREIMB_IP", "BENRES_IP", "PPPYMT_IP",
            "MEDREIMB_OP", "BENRES_OP", "PPPYMT_OP",
        ]
    ),
    AnomalyCheck(
        name="future_birth_date",
        table="beneficiary_summary",
        query="SELECT COUNT(*) FROM beneficiary_summary WHERE BENE_BIRTH_DT > 20250101",
        severity="high",
        column="BENE_BIRTH_DT",
    ),
    AnomalyCheck(
        name="invalid_sex_code",
        table="beneficiary_summary",
        query="SELECT COUNT(*) FROM beneficiary_summary WHERE BENE_SEX_IDENT_CD NOT IN (1, 2)",
        severity="medium",
        column="BENE_SEX_IDENT_CD",
    ),
)

# Match configurations for Steps 4-5
MATCH_CONFIGS: tuple[MatchConfig, ...] = (
    MatchConfig(
        old_table="beneficiary_summary",
        new_table="new_beneficiary_summary",
        key_cols=("DESYNPUF_ID", "summary_year"),
        compare_cols=(
            "BENE_BIRTH_DT", "BENE_DEATH_DT", "BENE_SEX_IDENT_CD", "BENE_RACE_CD",
            "BENE_ESRD_IND", "SP_STATE_CODE", "BENE_COUNTY_CD",
            "BENE_HI_CVRAGE_TOT_MONS", "BENE_SMI_CVRAGE_TOT_MONS",
            "BENE_HMO_CVRAGE_TOT_MONS", "PLAN_CVRG_MOS_NUM",
            "SP_ALZHDMTA", "SP_CHF", "SP_CHRNKIDN", "SP_CNCR", "SP_COPD",
            "SP_DEPRESSN", "SP_DIABETES", "SP_ISCHMCHT", "SP_OSTEOPRS",
            "SP_RA_OA", "SP_STRKETIA",
        ),
        numeric_cols=(
            "MEDREIMB_IP", "BENRES_IP", "PPPYMT_IP",
            "MEDREIMB_OP", "BENRES_OP", "PPPYMT_OP",
            "MEDREIMB_CAR", "BENRES_CAR", "PPPYMT_CAR",
        ),
        zset_table="_zset_beneficiary",
    ),
    MatchConfig(
        old_table="carrier_claims",
        new_table="new_carrier_claims",
        key_cols=("CLM_ID",),
        compare_cols=(
            "DESYNPUF_ID", "CLM_FROM_DT", "CLM_THRU_DT",
            "ICD9_DGNS_CD_1", "ICD9_DGNS_CD_2", "ICD9_DGNS_CD_3",
            "ICD9_DGNS_CD_4", "ICD9_DGNS_CD_5", "ICD9_DGNS_CD_6",
            "ICD9_DGNS_CD_7", "ICD9_DGNS_CD_8",
        ),
        numeric_cols=(
            "LINE_NCH_PMT_AMT_1", "LINE_NCH_PMT_AMT_2", "LINE_NCH_PMT_AMT_3",
            "LINE_NCH_PMT_AMT_4", "LINE_NCH_PMT_AMT_5",
            "LINE_BENE_PTB_DDCTBL_AMT_1", "LINE_BENE_PTB_DDCTBL_AMT_2",
            "LINE_BENE_PTB_DDCTBL_AMT_3",
        ),
        zset_table="_zset_claims",
    ),
)


__all__ = [
    "IngestOp",
    "IngestPlan",
    "AnomalyCheck",
    "AnomalyResult",
    "ValidationRule",
    "ValidationOutcome",
    "MatchConfig",
    "ExportOp",
    "ReportPlan",
    "ANOMALY_CHECKS",
    "MATCH_CONFIGS",
]
