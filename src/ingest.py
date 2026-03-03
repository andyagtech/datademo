"""
INGEST stage — Scan raw CSVs into DuckDB tables.

Uses DuckDB's native CSV reader for efficient zero-copy scanning where possible.
Creates persistent tables for beneficiary summaries and carrier claims.
"""

import os
import re
import logging
from pathlib import Path

import duckdb

logger = logging.getLogger(__name__)

RAW_DIR = Path(__file__).resolve().parent.parent / "data" / "raw"
DB_DIR = Path(__file__).resolve().parent.parent / "data" / "db"
DB_PATH = DB_DIR / "cms_claims.duckdb"

BENEFICIARY_FILES = {
    2008: "DE1_0_2008_Beneficiary_Summary_File_Sample_1.csv",
    2009: "DE1_0_2009_Beneficiary_Summary_File_Sample_1.csv",
    2010: "DE1_0_2010_Beneficiary_Summary_File_Sample_1.csv",
}

CARRIER_CLAIMS_FILES = [
    "DE1_0_2008_to_2010_Carrier_Claims_Sample_1A.csv",
    "DE1_0_2008_to_2010_Carrier_Claims_Sample_1B.csv",
]


def get_connection(db_path: Path = DB_PATH) -> duckdb.DuckDBPyConnection:
    """Return a DuckDB connection, creating the db directory if needed."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return duckdb.connect(str(db_path))


def ingest_beneficiary_summaries(con: duckdb.DuckDBPyConnection) -> None:
    """Load all beneficiary summary CSVs into a single unified table."""
    logger.info("Ingesting beneficiary summary files...")

    con.execute("DROP TABLE IF EXISTS beneficiary_summary")

    parts = []
    for year, filename in sorted(BENEFICIARY_FILES.items()):
        csv_path = RAW_DIR / filename
        if not csv_path.exists():
            logger.warning(f"Missing file: {csv_path}")
            continue
        logger.info(f"  Reading {filename} (year={year})...")
        parts.append(
            f"SELECT *, {year} AS summary_year FROM read_csv_auto('{csv_path}', header=true, all_varchar=false)"
        )

    if not parts:
        raise FileNotFoundError("No beneficiary summary files found in data/raw/")

    union_query = " UNION ALL ".join(parts)
    con.execute(f"CREATE TABLE beneficiary_summary AS ({union_query})")

    count = con.execute("SELECT COUNT(*) FROM beneficiary_summary").fetchone()[0]
    logger.info(f"  Loaded {count:,} beneficiary summary records.")


def ingest_carrier_claims(con: duckdb.DuckDBPyConnection) -> None:
    """Load carrier claims CSVs into a single table."""
    logger.info("Ingesting carrier claims files...")

    con.execute("DROP TABLE IF EXISTS carrier_claims")

    parts = []
    for filename in CARRIER_CLAIMS_FILES:
        csv_path = RAW_DIR / filename
        if not csv_path.exists():
            logger.warning(f"Missing file: {csv_path}")
            continue
        logger.info(f"  Reading {filename}...")
        parts.append(
            f"SELECT * FROM read_csv_auto('{csv_path}', header=true, all_varchar=false)"
        )

    if not parts:
        raise FileNotFoundError("No carrier claims files found in data/raw/")

    union_query = " UNION ALL ".join(parts)
    con.execute(f"CREATE TABLE carrier_claims AS ({union_query})")

    count = con.execute("SELECT COUNT(*) FROM carrier_claims").fetchone()[0]
    logger.info(f"  Loaded {count:,} carrier claims records.")


def _extract_year_from_filename(filename: str) -> int | None:
    """Extract the year from a beneficiary filename like DE1_0_2008_Beneficiary_..."""
    match = re.search(r"DE1_0_(\d{4})_Beneficiary", filename)
    return int(match.group(1)) if match else None


def ingest_new_system(con: duckdb.DuckDBPyConnection, new_data_dir: Path) -> None:
    """
    Load new-system data when available.
    Expects CSVs with the same schema placed in new_data_dir.
    Creates tables prefixed with 'new_' (e.g. new_beneficiary_summary, new_carrier_claims).
    """
    logger.info(f"Ingesting new system data from {new_data_dir}...")

    # --- Beneficiary files (need summary_year column to match old system schema) ---
    bene_matches = sorted(new_data_dir.glob("*Beneficiary*"))
    if bene_matches:
        con.execute("DROP TABLE IF EXISTS new_beneficiary_summary")
        parts = []
        for p in bene_matches:
            year = _extract_year_from_filename(p.name)
            if year:
                parts.append(
                    f"SELECT *, {year} AS summary_year FROM read_csv_auto('{p}', header=true, all_varchar=false)"
                )
            else:
                logger.warning(f"  Could not extract year from {p.name}, skipping summary_year")
                parts.append(
                    f"SELECT * FROM read_csv_auto('{p}', header=true, all_varchar=false)"
                )
        con.execute(f"CREATE TABLE new_beneficiary_summary AS ({' UNION ALL '.join(parts)})")
        count = con.execute("SELECT COUNT(*) FROM new_beneficiary_summary").fetchone()[0]
        logger.info(f"  Loaded {count:,} records into new_beneficiary_summary.")
    else:
        logger.warning(f"  No beneficiary files found in {new_data_dir}")

    # --- Carrier claims files (no extra columns needed) ---
    carrier_matches = sorted(new_data_dir.glob("*Carrier*"))
    if carrier_matches:
        con.execute("DROP TABLE IF EXISTS new_carrier_claims")
        parts = [
            f"SELECT * FROM read_csv_auto('{p}', header=true, all_varchar=false)"
            for p in carrier_matches
        ]
        con.execute(f"CREATE TABLE new_carrier_claims AS ({' UNION ALL '.join(parts)})")
        count = con.execute("SELECT COUNT(*) FROM new_carrier_claims").fetchone()[0]
        logger.info(f"  Loaded {count:,} records into new_carrier_claims.")
    else:
        logger.warning(f"  No carrier claims files found in {new_data_dir}")


def run(con: duckdb.DuckDBPyConnection | None = None, new_data_dir: Path | None = None) -> duckdb.DuckDBPyConnection:
    """Execute the full ingest pipeline."""
    if con is None:
        con = get_connection()

    ingest_beneficiary_summaries(con)
    ingest_carrier_claims(con)

    if new_data_dir and new_data_dir.exists():
        ingest_new_system(con, new_data_dir)

    logger.info("Ingest complete.")
    return con
