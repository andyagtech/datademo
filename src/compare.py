"""
COMPARE stage — Old system vs New system comparison framework.

Pluggable design: when new system data is loaded (tables prefixed with 'new_'),
this module compares them against the legacy tables and produces discrepancy metrics.

Comparison categories:
  1. Schema comparison — column presence, types
  2. Row-level diffing — missing/extra rows by key
  3. Field-level diffing — value mismatches on matched rows
  4. Aggregate divergence — summary statistics comparison
"""

import logging
from dataclasses import dataclass, field
from typing import TypedDict

import duckdb

from src.db_utils import table_exists as _table_exists

logger = logging.getLogger(__name__)


@dataclass
class ComparisonResult:
    check_name: str
    category: str  # schema, row_level, field_level, aggregate
    table_pair: str  # e.g. "beneficiary_summary vs new_beneficiary_summary"
    description: str
    metric_value: float | int
    details: list[dict] = field(default_factory=list)


def compare_schemas(
    con: duckdb.DuckDBPyConnection, old_table: str, new_table: str
) -> list[ComparisonResult]:
    """Compare column schemas between old and new tables."""
    results = []
    pair = f"{old_table} vs {new_table}"

    old_cols = {
        row[0]: row[1]
        for row in con.execute(
            f"SELECT column_name, data_type FROM information_schema.columns "
            f"WHERE table_name='{old_table}'"
        ).fetchall()
    }
    new_cols = {
        row[0]: row[1]
        for row in con.execute(
            f"SELECT column_name, data_type FROM information_schema.columns "
            f"WHERE table_name='{new_table}'"
        ).fetchall()
    }

    missing_in_new = set(old_cols) - set(new_cols)
    extra_in_new = set(new_cols) - set(old_cols)
    type_mismatches = [
        {"column": c, "old_type": old_cols[c], "new_type": new_cols[c]}
        for c in set(old_cols) & set(new_cols)
        if old_cols[c] != new_cols[c]
    ]

    results.append(ComparisonResult(
        check_name="missing_columns_in_new",
        category="schema",
        table_pair=pair,
        description="Columns present in old system but missing in new system",
        metric_value=len(missing_in_new),
        details=[{"columns": sorted(missing_in_new)}] if missing_in_new else [],
    ))
    results.append(ComparisonResult(
        check_name="extra_columns_in_new",
        category="schema",
        table_pair=pair,
        description="Columns present in new system but not in old system",
        metric_value=len(extra_in_new),
        details=[{"columns": sorted(extra_in_new)}] if extra_in_new else [],
    ))
    results.append(ComparisonResult(
        check_name="type_mismatches",
        category="schema",
        table_pair=pair,
        description="Columns with different data types between systems",
        metric_value=len(type_mismatches),
        details=type_mismatches,
    ))

    return results


def compare_row_counts(
    con: duckdb.DuckDBPyConnection, old_table: str, new_table: str, key_col: str
) -> list[ComparisonResult]:
    """Compare row presence between old and new by key."""
    results = []
    pair = f"{old_table} vs {new_table}"

    old_count = con.execute(f"SELECT COUNT(*) FROM {old_table}").fetchone()[0]
    new_count = con.execute(f"SELECT COUNT(*) FROM {new_table}").fetchone()[0]

    results.append(ComparisonResult(
        check_name="row_count_difference",
        category="row_level",
        table_pair=pair,
        description=f"Row count: old={old_count:,}, new={new_count:,}",
        metric_value=abs(old_count - new_count),
        details=[{"old_count": old_count, "new_count": new_count}],
    ))

    # Rows in old but not new
    missing = con.execute(f"""
        SELECT COUNT(DISTINCT o.{key_col})
        FROM {old_table} o
        LEFT JOIN {new_table} n ON o.{key_col} = n.{key_col}
        WHERE n.{key_col} IS NULL
    """).fetchone()[0]

    # Rows in new but not old
    extra = con.execute(f"""
        SELECT COUNT(DISTINCT n.{key_col})
        FROM {new_table} n
        LEFT JOIN {old_table} o ON n.{key_col} = o.{key_col}
        WHERE o.{key_col} IS NULL
    """).fetchone()[0]

    results.append(ComparisonResult(
        check_name="keys_missing_in_new",
        category="row_level",
        table_pair=pair,
        description=f"Distinct {key_col} values in old but not in new",
        metric_value=missing,
    ))
    results.append(ComparisonResult(
        check_name="keys_extra_in_new",
        category="row_level",
        table_pair=pair,
        description=f"Distinct {key_col} values in new but not in old",
        metric_value=extra,
    ))

    return results


def compare_field_values(
    con: duckdb.DuckDBPyConnection,
    old_table: str,
    new_table: str,
    key_col: str,
    compare_cols: list[str],
) -> list[ComparisonResult]:
    """Compare specific field values on matched rows."""
    results = []
    pair = f"{old_table} vs {new_table}"

    for col in compare_cols:
        safe_col = f'"{col}"'
        r = con.execute(f"""
            SELECT
                COUNT(*) AS matched_rows,
                SUM(CASE WHEN o.{safe_col}::VARCHAR IS DISTINCT FROM n.{safe_col}::VARCHAR
                    THEN 1 ELSE 0 END) AS mismatches
            FROM {old_table} o
            INNER JOIN {new_table} n ON o.{key_col} = n.{key_col}
        """).fetchone()
        assert r is not None
        matched, mismatches = r
        results.append(ComparisonResult(
            check_name=f"field_mismatch_{col.lower()}",
            category="field_level",
            table_pair=pair,
            description=f"Value mismatches for column {col} on matched rows",
            metric_value=mismatches,
            details=[{
                "matched_rows": matched,
                "mismatch_count": mismatches,
                "mismatch_pct": round(100.0 * mismatches / max(matched, 1), 2),
            }],
        ))

    return results


def compare_aggregates(
    con: duckdb.DuckDBPyConnection,
    old_table: str,
    new_table: str,
    numeric_cols: list[str],
) -> list[ComparisonResult]:
    """Compare aggregate statistics (sum, mean) for numeric columns."""
    results = []
    pair = f"{old_table} vs {new_table}"

    for col in numeric_cols:
        safe_col = f'"{col}"'
        old_stats = con.execute(f"""
            SELECT SUM({safe_col}::DOUBLE), AVG({safe_col}::DOUBLE)
            FROM {old_table} WHERE {safe_col} IS NOT NULL
        """).fetchone()
        new_stats = con.execute(f"""
            SELECT SUM({safe_col}::DOUBLE), AVG({safe_col}::DOUBLE)
            FROM {new_table} WHERE {safe_col} IS NOT NULL
        """).fetchone()

        sum_diff = abs((old_stats[0] or 0) - (new_stats[0] or 0))
        avg_diff = abs((old_stats[1] or 0) - (new_stats[1] or 0))

        results.append(ComparisonResult(
            check_name=f"aggregate_divergence_{col.lower()}",
            category="aggregate",
            table_pair=pair,
            description=f"Aggregate comparison for {col}",
            metric_value=sum_diff,
            details=[{
                "old_sum": round(old_stats[0] or 0, 2),
                "new_sum": round(new_stats[0] or 0, 2),
                "sum_diff": round(sum_diff, 2),
                "old_avg": round(old_stats[1] or 0, 2),
                "new_avg": round(new_stats[1] or 0, 2),
                "avg_diff": round(avg_diff, 2),
            }],
        ))

    return results


# --- Table pair configurations ---


class _TablePairConfig(TypedDict):
    """Configuration for comparing an old/new table pair."""
    old: str
    new: str
    key: str
    compare_cols: list[str]
    numeric_cols: list[str]


TABLE_PAIRS: list[_TablePairConfig] = [
    {
        "old": "beneficiary_summary",
        "new": "new_beneficiary_summary",
        "key": "DESYNPUF_ID",
        "compare_cols": [
            "BENE_BIRTH_DT", "BENE_DEATH_DT", "BENE_SEX_IDENT_CD", "BENE_RACE_CD",
            "SP_ALZHDMTA", "SP_CHF", "SP_CHRNKIDN", "SP_CNCR", "SP_COPD",
            "SP_DEPRESSN", "SP_DIABETES", "SP_ISCHMCHT", "SP_OSTEOPRS", "SP_RA_OA",
            "SP_STRKETIA",
        ],
        "numeric_cols": [
            "MEDREIMB_IP", "BENRES_IP", "PPPYMT_IP",
            "MEDREIMB_OP", "BENRES_OP", "PPPYMT_OP",
            "MEDREIMB_CAR", "BENRES_CAR", "PPPYMT_CAR",
        ],
    },
    {
        "old": "carrier_claims",
        "new": "new_carrier_claims",
        "key": "CLM_ID",
        "compare_cols": [
            "DESYNPUF_ID", "CLM_FROM_DT", "CLM_THRU_DT",
            "ICD9_DGNS_CD_1", "ICD9_DGNS_CD_2",
            "HCPCS_CD_1",
        ],
        "numeric_cols": [
            "LINE_NCH_PMT_AMT_1", "LINE_BENE_PTB_DDCTBL_AMT_1",
            "LINE_COINSRNC_AMT_1", "LINE_ALOWD_CHRG_AMT_1",
        ],
    },
]


def run(con: duckdb.DuckDBPyConnection) -> list[ComparisonResult]:
    """Execute all comparisons for available table pairs."""
    all_results = []

    for pair_cfg in TABLE_PAIRS:
        old_t, new_t = pair_cfg["old"], pair_cfg["new"]

        if not _table_exists(con, new_t):
            logger.info(
                f"Skipping comparison {old_t} vs {new_t} — new system table not loaded."
            )
            continue

        logger.info(f"Comparing {old_t} vs {new_t}...")

        all_results.extend(compare_schemas(con, old_t, new_t))
        all_results.extend(compare_row_counts(con, old_t, new_t, pair_cfg["key"]))
        all_results.extend(
            compare_field_values(con, old_t, new_t, pair_cfg["key"], pair_cfg["compare_cols"])
        )
        all_results.extend(
            compare_aggregates(con, old_t, new_t, pair_cfg["numeric_cols"])
        )

    if not all_results:
        logger.info("No new-system tables found. Comparison stage skipped — load new system data to enable.")
    else:
        logger.info(f"Comparison complete: {len(all_results)} checks run.")

    return all_results
