"""
CMS Claims Comparison Pipeline — Main Orchestrator

6-Step Pipeline:
  1. RECEIVE    — Accept files, verify integrity, extract zips
  2. VALIDATE   — Schema validation gate
  3. INGEST     — Load into DuckDB, profile data quality
  4. MATCH      — Record matching by primary keys
  5. COMPARE    — Field-level diffs, trend analysis
  6. REPORT     — Generate HTML report

Usage:
    python -m src.main                     # Run full pipeline on legacy data
    python -m src.main --new-data path/    # Include new system data for comparison
    python -m src.main --skip-ingest       # Skip ingest (reuse existing DB)
"""

import argparse
import logging
import sys
from pathlib import Path

from src.adapters.local import LocalStorage
from src.pipeline import PipelineContext
from src.pipeline.runner import run_pipeline
from src.ingest import DB_PATH, get_connection

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("pipeline")

RAW_DIR = Path(__file__).resolve().parent.parent / "data" / "raw"


def main() -> None:
    parser = argparse.ArgumentParser(description="CMS Claims Comparison Pipeline")
    parser.add_argument(
        "--new-data",
        type=str,
        default=None,
        help="Path to directory or zip file containing new system CSV files",
    )
    parser.add_argument(
        "--skip-ingest",
        action="store_true",
        help="Skip ingest stage and reuse existing DuckDB database",
    )
    parser.add_argument(
        "--db-path",
        type=str,
        default=None,
        help="Path to DuckDB database file (default: data/db/cms_claims.duckdb)",
    )
    args = parser.parse_args()

    new_data_dir = Path(args.new_data) if args.new_data else None
    db_path = Path(args.db_path) if args.db_path else DB_PATH

    # Build pipeline context with local storage adapter
    data_dir = RAW_DIR.parent  # data/ directory (has raw/ inside)
    storage = LocalStorage(base_dir=data_dir)

    ctx = PipelineContext(
        old_data_dir=data_dir,
        new_data_dir=new_data_dir,
        db_path=db_path,
        storage=storage,
        skip_ingest=args.skip_ingest,
        mode="local",
    )

    # If skipping ingest, pre-connect so step 3 reuses the connection
    if args.skip_ingest:
        if not db_path.exists():
            logger.error(f"Database not found at {db_path}. Run without --skip-ingest first.")
            sys.exit(1)
        ctx.con = get_connection(db_path)

    # Run the 6-step pipeline
    results = run_pipeline(ctx)

    # Exit with error code if pipeline halted
    if ctx.halted:
        sys.exit(1)

    if ctx.con:
        ctx.con.close()


if __name__ == "__main__":
    main()
