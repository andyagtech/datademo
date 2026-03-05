"""
PROFILE stage — Data quality profiling on ingested tables.

Generates per-table statistics: row counts, null rates, type distribution,
value ranges for numeric/date columns, and cardinality for categorical columns.
"""

import logging
from dataclasses import dataclass, field

import duckdb

logger = logging.getLogger(__name__)


@dataclass
class ColumnProfile:
    name: str
    dtype: str
    null_count: int
    null_pct: float
    distinct_count: int
    min_val: str | None = None
    max_val: str | None = None
    mean_val: float | None = None
    top_values: list[tuple[str, int]] = field(default_factory=list)


@dataclass
class TableProfile:
    table_name: str
    row_count: int
    column_count: int
    columns: list[ColumnProfile] = field(default_factory=list)


def profile_table(con: duckdb.DuckDBPyConnection, table_name: str) -> TableProfile:
    """Generate a quality profile for a single table."""
    logger.info(f"Profiling table: {table_name}")

    row_count = con.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]

    cols_info = con.execute(
        f"SELECT column_name, data_type FROM information_schema.columns "
        f"WHERE table_name = '{table_name}' ORDER BY ordinal_position"
    ).fetchall()

    tp = TableProfile(
        table_name=table_name,
        row_count=row_count,
        column_count=len(cols_info),
    )

    for col_name, col_type in cols_info:
        safe_col = f'"{col_name}"'

        try:
            stats = con.execute(f"""
                SELECT
                    COUNT(*) - COUNT({safe_col}) AS null_count,
                    ROUND(100.0 * (COUNT(*) - COUNT({safe_col})) / COUNT(*), 2) AS null_pct,
                    COUNT(DISTINCT {safe_col}) AS distinct_count
                FROM {table_name}
            """).fetchone()

            cp = ColumnProfile(
                name=col_name,
                dtype=col_type,
                null_count=stats[0],
                null_pct=stats[1],
                distinct_count=stats[2],
            )

            is_numeric = any(t in col_type.upper() for t in [
                "INT", "BIGINT", "DOUBLE", "FLOAT", "DECIMAL", "NUMERIC", "HUGEINT", "SMALLINT", "TINYINT"
            ])

            if is_numeric:
                num_stats = con.execute(f"""
                    SELECT
                        MIN({safe_col})::VARCHAR,
                        MAX({safe_col})::VARCHAR,
                        AVG({safe_col}::DOUBLE)
                    FROM {table_name}
                    WHERE {safe_col} IS NOT NULL
                """).fetchone()
                cp.min_val = num_stats[0]
                cp.max_val = num_stats[1]
                cp.mean_val = num_stats[2]

            if cp.distinct_count <= 30 and cp.distinct_count > 0:
                top = con.execute(f"""
                    SELECT {safe_col}::VARCHAR AS val, COUNT(*) AS cnt
                    FROM {table_name}
                    WHERE {safe_col} IS NOT NULL
                    GROUP BY val
                    ORDER BY cnt DESC
                    LIMIT 10
                """).fetchall()
                cp.top_values = [(str(v), c) for v, c in top]

        except Exception as e:
            logger.warning(f"Could not profile column {col_name} in {table_name}: {e}")
            cp = ColumnProfile(name=col_name, dtype=col_type, null_count=0, null_pct=0, distinct_count=0)

        tp.columns.append(cp)

    logger.info(
        f"  {table_name}: {row_count:,} rows, {len(cols_info)} cols, "
        f"high-null cols: {sum(1 for c in tp.columns if c.null_pct > 50)}"
    )
    return tp


def run(con: duckdb.DuckDBPyConnection) -> dict[str, TableProfile]:
    """Profile all ingested tables."""
    tables = con.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'"
    ).fetchall()

    profiles = {}
    for (table_name,) in tables:
        profiles[table_name] = profile_table(con, table_name)

    logger.info(f"Profiling complete — {len(profiles)} tables profiled.")
    return profiles
