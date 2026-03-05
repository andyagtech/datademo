"""Shared DuckDB utility functions used across pipeline steps."""

import duckdb


def table_exists(con: duckdb.DuckDBPyConnection, table_name: str) -> bool:
    """Check if a table exists in the main schema."""
    r = con.execute(
        "SELECT COUNT(*) FROM information_schema.tables "
        "WHERE table_schema = 'main' AND table_name = ?",
        [table_name],
    ).fetchone()
    return r[0] > 0
