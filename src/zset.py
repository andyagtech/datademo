"""
Z-Set Algebra for Data Pipeline Diffing

A Z-set (from DBSP theory, as used by Feldera) is a multiset with integer
weights forming an abelian group under pointwise addition:

    Z: D → ℤ

    - A database table is a Z-set where every row has weight +1
    - INSERT = add rows with weight +1
    - DELETE = add rows with weight -1
    - DIFF   = new - old (produces +1 for insertions, -1 for deletions)
    - MERGE  = combine two Z-sets by summing weights

This module implements Z-sets as DuckDB SQL operations. The descriptions
are pure (frozen dataclasses); only the interpreter touches the database.

Reference: Budiu et al., "DBSP: Automatic Incremental View Maintenance" (VLDB 2023)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import duckdb

from src.functional import Result, try_op

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pure descriptions (no I/O)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class TableRef:
    """Immutable reference to a DuckDB table."""
    name: str
    key_cols: tuple[str, ...]
    value_cols: tuple[str, ...] = ()

    @property
    def all_cols(self) -> tuple[str, ...]:
        return self.key_cols + self.value_cols


@dataclass(frozen=True)
class ZSetView:
    """
    A Z-set backed by a DuckDB table with a _weight column.

    Rows with _weight > 0 are insertions (present in new but not old).
    Rows with _weight < 0 are deletions (present in old but not new).
    Rows with _weight = 0 cancel out (identical in both systems).
    """
    table_name: str
    key_cols: tuple[str, ...]
    value_cols: tuple[str, ...] = ()

    @property
    def insertions_sql(self) -> str:
        """SQL for rows that exist only in the new system."""
        return f"SELECT * FROM {self.table_name} WHERE _weight > 0"

    @property
    def deletions_sql(self) -> str:
        """SQL for rows that exist only in the old system."""
        return f"SELECT * FROM {self.table_name} WHERE _weight < 0"

    @property
    def changes_sql(self) -> str:
        """SQL for all non-zero-weight rows (the actual diff)."""
        return f"SELECT * FROM {self.table_name} WHERE _weight != 0"


@dataclass(frozen=True)
class ZSetStats:
    """Immutable statistics computed from a Z-set."""
    total_rows: int
    insertions: int     # weight > 0
    deletions: int      # weight < 0
    unchanged: int      # weight = 0 (cancelled out)
    net_change: int     # insertions - deletions

    @property
    def change_rate_pct(self) -> float:
        denom = self.total_rows or 1
        return round(100.0 * (self.insertions + self.deletions) / denom, 2)


@dataclass(frozen=True)
class FieldDelta:
    """Immutable field-level diff statistics."""
    column: str
    mismatches: int
    total_matched: int
    mismatch_pct: float
    # For numeric fields
    sum_abs_delta: float | None = None
    avg_abs_delta: float | None = None
    max_abs_delta: float | None = None


@dataclass(frozen=True)
class ZSetDiffResult:
    """Complete result of a Z-set diff operation."""
    old_ref: TableRef
    new_ref: TableRef
    zset: ZSetView
    stats: ZSetStats
    field_deltas: tuple[FieldDelta, ...] = ()

    def to_legacy_dict(self) -> dict:
        return {
            "old_table": self.old_ref.name,
            "new_table": self.new_ref.name,
            "zset_table": self.zset.table_name,
            "total_records": self.stats.total_rows,
            "matched": self.stats.unchanged,
            "old_only": self.stats.deletions,
            "new_only": self.stats.insertions,
            "match_rate": round(
                100.0 * self.stats.unchanged /
                max(self.stats.total_rows, 1), 2
            ),
            "field_deltas": [
                {
                    "column": fd.column,
                    "mismatches": fd.mismatches,
                    "total_matched": fd.total_matched,
                    "mismatch_pct": fd.mismatch_pct,
                    "sum_abs_delta": fd.sum_abs_delta,
                }
                for fd in self.field_deltas
            ],
        }


# ---------------------------------------------------------------------------
# Pure SQL generators (no execution — just string building)
# ---------------------------------------------------------------------------

def diff_sql(
    old: TableRef,
    new: TableRef,
    result_table: str,
) -> str:
    """
    Generate SQL for a Z-set diff: new - old.

    Uses FULL OUTER JOIN to produce a table with _weight:
      +1 = in new only (insertion)
      -1 = in old only (deletion)
       0 = in both (matched, cancelled out — but we keep for stats)

    This is the core DBSP operation Δ(R) = R_new - R_old.
    """
    key_join = " AND ".join(
        f"CAST(o.{k} AS VARCHAR) = CAST(n.{k} AS VARCHAR)"
        for k in old.key_cols
    )
    key_coalesce = ", ".join(
        f"COALESCE(CAST(o.{k} AS VARCHAR), CAST(n.{k} AS VARCHAR)) AS {k}"
        for k in old.key_cols
    )
    old_null = f"o.{old.key_cols[0]} IS NULL"
    new_null = f"n.{new.key_cols[0]} IS NULL"

    return f"""
    DROP TABLE IF EXISTS {result_table};
    CREATE TABLE {result_table} AS
    SELECT
        {key_coalesce},
        CASE
            WHEN {old_null} THEN 1     -- insertion (new only)
            WHEN {new_null} THEN -1    -- deletion (old only)
            ELSE 0                     -- matched (cancels out)
        END AS _weight,
        CASE
            WHEN {old_null} THEN 'new_only'
            WHEN {new_null} THEN 'old_only'
            ELSE 'matched'
        END AS _status
    FROM {old.name} o
    FULL OUTER JOIN {new.name} n ON {key_join}
    """


def field_diff_sql(
    old: TableRef,
    new: TableRef,
    columns: tuple[str, ...],
    is_numeric: bool = False,
) -> str:
    """
    Generate SQL for field-level diff on matched rows.

    For each column, computes mismatch count.
    For numeric columns, also computes sum/avg/max of absolute deltas.
    """
    key_join = " AND ".join(f"o.{k} = n.{k}" for k in old.key_cols)
    parts = ["SELECT COUNT(*) AS total_matched"]

    for col in columns:
        safe = f'"{col}"'
        parts.append(
            f"SUM(CASE WHEN o.{safe}::VARCHAR IS DISTINCT FROM n.{safe}::VARCHAR "
            f"THEN 1 ELSE 0 END) AS mismatch_{col.lower()}"
        )
        if is_numeric:
            parts.append(
                f"SUM(ABS(COALESCE(o.{safe}::DOUBLE,0) - COALESCE(n.{safe}::DOUBLE,0))) "
                f"AS delta_sum_{col.lower()}"
            )
            parts.append(
                f"AVG(ABS(COALESCE(o.{safe}::DOUBLE,0) - COALESCE(n.{safe}::DOUBLE,0))) "
                f"AS delta_avg_{col.lower()}"
            )
            parts.append(
                f"MAX(ABS(COALESCE(o.{safe}::DOUBLE,0) - COALESCE(n.{safe}::DOUBLE,0))) "
                f"AS delta_max_{col.lower()}"
            )

    return (
        ", ".join(parts) +
        f" FROM {old.name} o INNER JOIN {new.name} n ON {key_join}"
    )


def stats_sql(zset_table: str) -> str:
    """Generate SQL for Z-set statistics."""
    return f"""
    SELECT
        COUNT(*) AS total_rows,
        SUM(CASE WHEN _weight > 0 THEN 1 ELSE 0 END) AS insertions,
        SUM(CASE WHEN _weight < 0 THEN 1 ELSE 0 END) AS deletions,
        SUM(CASE WHEN _weight = 0 THEN 1 ELSE 0 END) AS unchanged,
        SUM(_weight) AS net_change
    FROM {zset_table}
    """


# ---------------------------------------------------------------------------
# Interpreter: execute pure descriptions against DuckDB
# ---------------------------------------------------------------------------

def execute_diff(
    con: duckdb.DuckDBPyConnection,
    old: TableRef,
    new: TableRef,
    result_table: str,
    compare_cols: tuple[str, ...] = (),
    numeric_cols: tuple[str, ...] = (),
) -> Result[ZSetDiffResult, Exception]:
    """
    Execute a Z-set diff: new - old.

    This is the only function that touches the database.
    Everything above is pure SQL generation.
    """
    def _execute() -> ZSetDiffResult:
        # 1. Create the diff table (Z-set)
        sql = diff_sql(old, new, result_table)
        for stmt in sql.strip().split(";"):
            stmt = stmt.strip()
            if stmt:
                con.execute(stmt)

        # 2. Compute stats
        row = con.execute(stats_sql(result_table)).fetchone()
        zstats = ZSetStats(
            total_rows=row[0],
            insertions=row[1],
            deletions=row[2],
            unchanged=row[3],
            net_change=row[4],
        )

        # 3. Field-level diffs on matched rows
        deltas: list[FieldDelta] = []
        all_compare = compare_cols + numeric_cols
        if all_compare:
            # Non-numeric field diffs
            if compare_cols:
                sql = field_diff_sql(old, new, compare_cols, is_numeric=False)
                row = con.execute(sql).fetchone()
                total_matched = row[0]
                for i, col in enumerate(compare_cols):
                    mismatches = row[1 + i]
                    deltas.append(FieldDelta(
                        column=col,
                        mismatches=mismatches,
                        total_matched=total_matched,
                        mismatch_pct=round(100.0 * mismatches / max(total_matched, 1), 2),
                    ))

            # Numeric field diffs (with dollar deltas)
            if numeric_cols:
                sql = field_diff_sql(old, new, numeric_cols, is_numeric=True)
                row = con.execute(sql).fetchone()
                total_matched = row[0]
                for i, col in enumerate(numeric_cols):
                    base = 1 + i * 4  # mismatch, sum, avg, max per col
                    mismatches = row[base]
                    deltas.append(FieldDelta(
                        column=col,
                        mismatches=mismatches,
                        total_matched=total_matched,
                        mismatch_pct=round(100.0 * mismatches / max(total_matched, 1), 2),
                        sum_abs_delta=round(row[base + 1] or 0, 2),
                        avg_abs_delta=round(row[base + 2] or 0, 4),
                        max_abs_delta=round(row[base + 3] or 0, 2),
                    ))

        zset_view = ZSetView(
            table_name=result_table,
            key_cols=old.key_cols,
            value_cols=old.value_cols,
        )

        return ZSetDiffResult(
            old_ref=old,
            new_ref=new,
            zset=zset_view,
            stats=zstats,
            field_deltas=tuple(deltas),
        )

    return try_op(_execute)


# ---------------------------------------------------------------------------
# Convenience: Z-set operations as composable functions
# ---------------------------------------------------------------------------

def table_to_ref(
    con: duckdb.DuckDBPyConnection,
    table_name: str,
    key_cols: tuple[str, ...],
) -> Result[TableRef, Exception]:
    """Create a TableRef, verifying the table exists."""
    def _check() -> TableRef:
        exists = con.execute(
            f"SELECT COUNT(*) FROM information_schema.tables "
            f"WHERE table_name = '{table_name}'"
        ).fetchone()[0]
        if not exists:
            raise ValueError(f"Table '{table_name}' does not exist")

        # Discover value columns (all cols minus key cols)
        all_cols = [
            row[0] for row in con.execute(
                f"SELECT column_name FROM information_schema.columns "
                f"WHERE table_name = '{table_name}' ORDER BY ordinal_position"
            ).fetchall()
        ]
        value_cols = tuple(c for c in all_cols if c not in key_cols)

        return TableRef(
            name=table_name,
            key_cols=key_cols,
            value_cols=value_cols,
        )

    return try_op(_check)


__all__ = [
    "TableRef",
    "ZSetView",
    "ZSetStats",
    "FieldDelta",
    "ZSetDiffResult",
    "diff_sql",
    "field_diff_sql",
    "stats_sql",
    "execute_diff",
    "table_to_ref",
]
