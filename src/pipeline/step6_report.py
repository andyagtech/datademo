"""
STEP 6: REPORT — Generate the final HTML report from all pipeline results.

Responsibilities:
  - Consume results from all prior steps
  - Generate interactive HTML report
  - Export raw diff data as CSV and Parquet for further analysis
"""

import logging
from pathlib import Path

from src.pipeline import PipelineContext, StepResult
from src.report import run as report_run

logger = logging.getLogger(__name__)


def run(ctx: PipelineContext) -> StepResult:
    """Execute Step 6: Report generation."""
    errors: list[str] = []
    warnings: list[str] = []

    profiles = ctx.results.get("profiles", {})
    validations = ctx.results.get("validations", [])
    comparisons = ctx.results.get("comparisons", [])
    con = ctx.con

    try:
        report_path = report_run(
            profiles, validations, comparisons,
            con=con, pipeline_results=ctx.results,
        )
    except Exception as e:
        return StepResult(
            step_name="report",
            success=False,
            message=f"Report generation failed: {e}",
            errors=[str(e)],
        )

    # Export raw diffs as CSV + Parquet if analysis tables exist
    csv_exports = []
    parquet_exports = []
    if con:
        try:
            tables = [r[0] for r in con.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_name LIKE '_discrepancy%' OR table_name LIKE '_match%' "
                "OR table_name LIKE '_financial_recon'"
            ).fetchall()]

            export_dir = report_path.parent / "exports"
            export_dir.mkdir(exist_ok=True)
            for t in tables:
                # CSV — human-readable, Excel-compatible
                csv_path = export_dir / f"{t}.csv"
                con.execute(f"COPY {t} TO '{csv_path}' (HEADER, DELIMITER ',')")
                csv_exports.append(str(csv_path))
                # Parquet — columnar, compressed, standard interchange format
                parquet_path = export_dir / f"{t}.parquet"
                con.execute(f"COPY {t} TO '{parquet_path}' (FORMAT PARQUET, COMPRESSION ZSTD)")
                parquet_exports.append(str(parquet_path))
                logger.info(f"Exported {t} → CSV + Parquet")
        except Exception as e:
            warnings.append(f"Data export failed: {e}")

    total_exports = len(csv_exports) + len(parquet_exports)
    ctx.results["report"] = {
        "report_path": str(report_path),
        "csv_exports": csv_exports,
        "parquet_exports": parquet_exports,
    }

    return StepResult(
        step_name="report",
        success=True,
        message=f"Report: {report_path}. {len(csv_exports)} CSV exports. {len(parquet_exports)} Parquet exports.",
        data=ctx.results["report"],
        errors=errors,
        warnings=warnings,
    )
