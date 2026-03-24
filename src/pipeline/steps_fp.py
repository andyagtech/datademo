"""
Functional Steps 3-6: Interpreter Pattern + Z-Set Algebra

Each step follows the same structure:
  1. Build a pure plan (immutable data describing what to do)
  2. Execute the plan via an interpreter (effectful boundary)
  3. Return an immutable StepOutcome

The DuckDB connection is the only effectful dependency — it's passed
at the boundary, not threaded through pure logic.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

import duckdb
from returns.maybe import Some

from src.functional import Result, Success, is_err, try_op
from src.pipeline import PipelineContext
from src.pipeline.state import PipelineConfig, PipelineState, StepOutcome
from src.pipeline.query_algebra import (
    IngestOp, IngestPlan,
    AnomalyCheck, AnomalyResult, ANOMALY_CHECKS,
    MATCH_CONFIGS,
    ExportOp, ReportPlan,
)
from src.zset import TableRef, execute_diff, ZSetDiffResult

logger = logging.getLogger("pipeline")


# ===================================================================
# Step 3: Ingest & Profile — Plan / Interpret / Summarize
# ===================================================================

def _build_ingest_plan(config: PipelineConfig) -> IngestPlan:
    """Pure: build an immutable ingest plan from pipeline config."""
    import re
    ops: list[IngestOp] = []
    old_dir = config.old_data_dir / "old_system"

    # Discover beneficiary CSVs
    for path in sorted(old_dir.glob("*Beneficiary*.csv")):
        m = re.search(r"DE1_0_(\d{4})_Beneficiary", path.name)
        year = int(m.group(1)) if m else None
        ops.append(IngestOp(
            source_path=path,
            target_table="beneficiary_summary",
            year_column=year,
        ))

    # Discover carrier CSVs
    for path in sorted(old_dir.glob("*Carrier*.csv")):
        ops.append(IngestOp(
            source_path=path,
            target_table="carrier_claims",
        ))

    # New system files
    match config.new_data_dir:
        case Some(new_dir):
            for path in sorted(new_dir.glob("*Beneficiary*.csv")):
                m = re.search(r"DE1_0_(\d{4})_Beneficiary", path.name)
                year = int(m.group(1)) if m else None
                ops.append(IngestOp(
                    source_path=path,
                    target_table="new_beneficiary_summary",
                    year_column=year,
                ))
            for path in sorted(new_dir.glob("*Carrier*.csv")):
                ops.append(IngestOp(
                    source_path=path,
                    target_table="new_carrier_claims",
                ))
        case _:
            pass

    return IngestPlan(
        operations=tuple(ops),
        skip_ingest=config.skip_ingest,
        db_path=config.db_path.value_or(None),
    )


def _execute_ingest_plan(
    plan: IngestPlan, ctx: PipelineContext,
) -> Result[duckdb.DuckDBPyConnection, Exception]:
    """Effectful: execute the ingest plan against DuckDB."""
    from src.ingest import get_connection, DB_PATH

    def _run() -> duckdb.DuckDBPyConnection:
        if plan.skip_ingest and ctx.con:
            logger.info("Reusing existing DB connection (skip_ingest=True)")
            return ctx.con

        db_path = plan.db_path or DB_PATH
        if plan.skip_ingest:
            if not db_path.exists():
                raise FileNotFoundError(
                    f"Database not found at {db_path}. Run without --skip-ingest."
                )
            con = get_connection(db_path)
            ctx.con = con
            logger.info(f"Connected to existing DB: {db_path}")
            return con

        con = get_connection(db_path)
        ctx.con = con

        # Group operations by target table
        by_table: dict[str, list[IngestOp]] = {}
        for op in plan.operations:
            by_table.setdefault(op.target_table, []).append(op)

        for table_name, ops in by_table.items():
            con.execute(f"DROP TABLE IF EXISTS {table_name}")
            parts = []
            for op in ops:
                if op.year_column is not None:
                    parts.append(
                        f"SELECT *, {op.year_column} AS summary_year "
                        f"FROM read_csv_auto('{op.source_path}', header=true, all_varchar=false)"
                    )
                else:
                    parts.append(
                        f"SELECT * FROM read_csv_auto('{op.source_path}', header=true, all_varchar=false)"
                    )
                logger.info(f"  Reading {op.source_path.name}...")

            union_query = " UNION ALL ".join(parts)
            con.execute(f"CREATE TABLE {table_name} AS ({union_query})")
            count = con.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]
            logger.info(f"  Loaded {count:,} records into {table_name}.")

        return con

    return try_op(_run)


def _execute_anomaly_checks(
    con: duckdb.DuckDBPyConnection,
    checks: tuple[AnomalyCheck, ...],
) -> tuple[AnomalyResult, ...]:
    """Effectful: run pure anomaly check descriptions against DuckDB."""
    results: list[AnomalyResult] = []
    for check in checks:
        try:
            row = con.execute(check.query).fetchone()
            results.append(AnomalyResult(check=check, count=row[0]))
        except duckdb.Error as e:
            logger.debug(f"Anomaly check skipped for {check.name}: {e}")
    return tuple(results)


def step3_functional(
    ctx: PipelineContext,
) -> callable:
    """Closure: returns a StepFunction that carries the ctx for DB access."""

    def _step(state: PipelineState) -> Result[PipelineState, Exception]:
        if state.should_halt():
            return Success(state)

        t0 = time.time()
        logger.info("=" * 60)
        logger.info("STEP 3. Ingest & Profile")
        logger.info("=" * 60)

        errors: list[str] = []
        warnings: list[str] = []

        # 1. Pure: build the plan
        plan = _build_ingest_plan(state.config)

        # 2. Effectful: execute the plan
        con_result = _execute_ingest_plan(plan, ctx)
        if is_err(con_result):
            elapsed = time.time() - t0
            msg = str(con_result.failure())
            logger.error(f"  ✗ {msg} ({elapsed:.1f}s)")
            outcome = StepOutcome.err("ingest", msg, (msg,))
            return Success(state.with_outcome(outcome))

        con = con_result.unwrap()

        # 3. Profile (effectful boundary)
        from src.profile import run as profile_run
        profiles = profile_run(con)
        ctx.results["profiles"] = profiles

        # 4. Anomaly detection (pure descriptions → effectful execution)
        anomaly_results = _execute_anomaly_checks(con, ANOMALY_CHECKS)
        anomalies = [r.to_dict() for r in anomaly_results if r.is_anomalous]
        ctx.results["anomalies"] = anomalies
        if anomalies:
            high = [a for a in anomalies if a["severity"] == "high"]
            if high:
                warnings.append(f"{len(high)} high-severity anomalies detected")

        # 5. Claim line utilization (effectful boundary)
        from src.pipeline.step3_ingest import _claim_line_utilization
        line_util = _claim_line_utilization(con)
        ctx.results["claim_line_utilization"] = line_util
        if line_util:
            logger.info(
                f"  Claim line utilization: avg={line_util['avg_lines']} lines/claim, "
                f"median={line_util['median_lines']}, "
                f"{line_util['pct_lte_3_lines']}% use ≤3 lines"
            )

        # 6. Counts
        try:
            bene_count = con.execute("SELECT COUNT(*) FROM beneficiary_summary").fetchone()[0]
            claim_count = con.execute("SELECT COUNT(*) FROM carrier_claims").fetchone()[0]
        except duckdb.Error:
            bene_count = 0
            claim_count = 0

        elapsed = time.time() - t0
        data = {
            "beneficiary_count": bene_count,
            "claims_count": claim_count,
            "anomalies": anomalies,
            "tables_profiled": len(profiles),
            "claim_line_utilization": line_util,
            "ingest_plan": {
                "operations": len(plan.operations),
                "tables": list(plan.table_names),
                "skip_ingest": plan.skip_ingest,
            },
        }
        ctx.results["ingest"] = data

        msg = (
            f"Ingested {bene_count:,} beneficiaries, {claim_count:,} claims. "
            f"Profiled {len(profiles)} tables. {len(anomalies)} anomalies."
        )
        status = "✓" if not errors else "✗"
        logger.info(f"  {status} {msg} ({elapsed:.1f}s)")
        for w in warnings:
            logger.warning(f"  ⚠ {w}")

        outcome = StepOutcome(
            step_name="ingest",
            success=len(errors) == 0,
            message=msg,
            data=data,
            errors=tuple(errors),
            warnings=tuple(warnings),
        )
        return Success(state.with_outcome(outcome))

    return _step


# ===================================================================
# Step 4: Match & Validate — Validation Rules + Z-Set Matching
# ===================================================================

def step4_functional(
    ctx: PipelineContext,
) -> callable:
    """Closure: returns a StepFunction for matching and validation."""

    def _step(state: PipelineState) -> Result[PipelineState, Exception]:
        if state.should_halt():
            return Success(state)

        t0 = time.time()
        logger.info("=" * 60)
        logger.info("STEP 4. Match & Validate")
        logger.info("=" * 60)

        assert ctx.con is not None, "Step 4 requires a DB connection"
        con = ctx.con
        warnings: list[str] = []

        # 1. Validation rules (delegate to existing validate.py at boundary)
        from src.validate import run as validate_run
        validations = validate_run(con)
        ctx.results["validations"] = validations

        passed = sum(1 for v in validations if v.passed)
        failed = len(validations) - passed
        if failed > 0:
            warnings.append(f"{failed} internal consistency check(s) failed on old system")

        # 2. Z-set matching (pure algebra → effectful execution)
        from src.db_utils import table_exists as _table_exists
        match_results: dict[str, dict] = {}
        has_new_data = False

        for cfg in MATCH_CONFIGS:
            if not _table_exists(con, cfg.new_table):
                logger.info(f"Skipping match for {cfg.old_table} — new table not loaded")
                continue

            has_new_data = True
            old_ref = TableRef(name=cfg.old_table, key_cols=cfg.key_cols)
            new_ref = TableRef(name=cfg.new_table, key_cols=cfg.key_cols)

            # Z-set diff: new - old
            zset_result = execute_diff(
                con, old_ref, new_ref, cfg.zset_table,
            )

            if is_err(zset_result):
                logger.warning(f"Z-set diff failed for {cfg.old_table}: {zset_result.failure()}")
                continue

            zr = zset_result.unwrap()
            legacy = zr.to_legacy_dict()
            match_results[cfg.old_table] = legacy

            logger.info(f"Matching {cfg.old_table} ↔ {cfg.new_table}...")
            logger.info(
                f"  {legacy['matched']:,} matched, "
                f"{legacy['old_only']:,} old-only, "
                f"{legacy['new_only']:,} new-only "
                f"({legacy['match_rate']}% match rate)"
            )

            # Also create the legacy _match_ tables for report compatibility
            if cfg.old_table == "beneficiary_summary":
                match_table = "_match_beneficiary"
            else:
                match_table = "_match_claims"

            con.execute(f"DROP TABLE IF EXISTS {match_table}")
            con.execute(f"""
                CREATE TABLE {match_table} AS
                SELECT *, _status AS match_status
                FROM {cfg.zset_table}
            """)

            if legacy["old_only"] > 0:
                warnings.append(
                    f"{legacy['old_only']:,} {cfg.old_table} records missing in new system"
                )
            if legacy["new_only"] > 0:
                warnings.append(
                    f"{legacy['new_only']:,} extra {cfg.old_table} records in new system"
                )

        elapsed = time.time() - t0
        data = {
            "match_results": match_results,
            "has_new_data": has_new_data,
            "validation_passed": passed,
            "validation_failed": failed,
            "validation_total": len(validations),
        }
        ctx.results["match"] = data

        msg_parts = [f"Validation: {passed}/{len(validations)} passed"]
        if has_new_data:
            for table, r in match_results.items():
                msg_parts.append(f"{table}: {r['match_rate']}% matched")
        else:
            msg_parts.append("No new system data for matching")

        msg = ". ".join(msg_parts)
        logger.info(f"  ✓ {msg} ({elapsed:.1f}s)")
        for w in warnings:
            logger.warning(f"  ⚠ {w}")

        outcome = StepOutcome(
            step_name="match",
            success=True,
            message=msg,
            data=data,
            errors=(),
            warnings=tuple(warnings),
        )
        return Success(state.with_outcome(outcome))

    return _step


# ===================================================================
# Step 5: Compare & Analyze — Z-Set Field Diffs + Trend Analysis
# ===================================================================

def _build_discrepancy_detail_zset(
    con: duckdb.DuckDBPyConnection,
) -> list[dict]:
    """
    Build discrepancy detail using Z-set field deltas.

    Instead of the imperative approach of building SQL strings,
    this uses the Z-set diff results already computed in Step 4
    plus the existing compare engine for detailed analysis.
    """
    from src.db_utils import table_exists as _table_exists
    if not _table_exists(con, "new_beneficiary_summary"):
        return []

    # Financial columns
    financial_cols = [
        "MEDREIMB_IP", "BENRES_IP", "PPPYMT_IP",
        "MEDREIMB_OP", "BENRES_OP", "PPPYMT_OP",
        "MEDREIMB_CAR", "BENRES_CAR", "PPPYMT_CAR",
    ]
    demo_cols = ["BENE_SEX_IDENT_CD", "BENE_RACE_CD", "BENE_BIRTH_DT", "BENE_DEATH_DT"]
    clinical_cols = [
        "SP_ALZHDMTA", "SP_CHF", "SP_CHRNKIDN", "SP_CNCR", "SP_COPD",
        "SP_DEPRESSN", "SP_DIABETES", "SP_ISCHMCHT", "SP_OSTEOPRS",
        "SP_RA_OA", "SP_STRKETIA",
    ]
    all_cols = financial_cols + demo_cols + clinical_cols

    try:
        # Build per-row discrepancy flags
        diff_exprs = []
        for col in all_cols:
            diff_exprs.append(
                f'CASE WHEN o."{col}"::VARCHAR IS DISTINCT FROM n."{col}"::VARCHAR '
                f"THEN 1 ELSE 0 END AS diff_{col.lower()}"
            )
        dollar_exprs = []
        for col in financial_cols:
            dollar_exprs.append(
                f'COALESCE(ABS(o."{col}"::DOUBLE - n."{col}"::DOUBLE), 0) AS delta_{col.lower()}'
            )

        con.execute("DROP TABLE IF EXISTS _discrepancy_detail")
        con.execute(f"""
            CREATE TABLE _discrepancy_detail AS
            SELECT
                o.DESYNPUF_ID,
                o.summary_year,
                o.SP_STATE_CODE,
                {', '.join(diff_exprs)},
                {', '.join(dollar_exprs)},
                ({' + '.join(f'diff_{c.lower()}' for c in all_cols)}) AS total_diffs
            FROM beneficiary_summary o
            INNER JOIN new_beneficiary_summary n
                ON o.DESYNPUF_ID = n.DESYNPUF_ID
                AND o.summary_year = n.summary_year
        """)

        trends = []

        # Overall mismatch rate
        r = con.execute("""
            SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN total_diffs > 0 THEN 1 ELSE 0 END) AS mismatched
            FROM _discrepancy_detail
        """).fetchone()
        trends.append({
            "trend": "overall_mismatch_rate",
            "total": r[0], "affected": r[1],
            "rate_pct": round(100.0 * r[1] / max(r[0], 1), 2),
        })

        # Mismatch by year
        for row in con.execute("""
            SELECT summary_year, COUNT(*), SUM(CASE WHEN total_diffs > 0 THEN 1 ELSE 0 END)
            FROM _discrepancy_detail GROUP BY summary_year ORDER BY summary_year
        """).fetchall():
            trends.append({
                "trend": f"mismatch_by_year_{row[0]}",
                "year": row[0], "total": row[1], "affected": row[2],
                "rate_pct": round(100.0 * row[2] / max(row[1], 1), 2),
            })

        # Financial impact by year
        for row in con.execute(f"""
            SELECT summary_year,
                SUM({' + '.join(f'delta_{c.lower()}' for c in financial_cols)}) AS total_dollar_impact
            FROM _discrepancy_detail GROUP BY summary_year ORDER BY summary_year
        """).fetchall():
            trends.append({
                "trend": f"financial_impact_{row[0]}",
                "year": row[0], "dollar_impact": round(row[1], 2),
            })

        # Most affected fields
        for col in all_cols:
            r = con.execute(f"SELECT SUM(diff_{col.lower()}) FROM _discrepancy_detail").fetchone()
            if r[0] and r[0] > 0:
                trends.append({
                    "trend": "field_mismatch_count",
                    "field": col, "mismatches": r[0],
                })

        return trends

    except Exception as e:
        logger.warning(f"Could not build discrepancy detail: {e}")
        return []


def step5_functional(
    ctx: PipelineContext,
) -> callable:
    """Closure: returns a StepFunction for comparison using Z-set algebra."""

    def _step(state: PipelineState) -> Result[PipelineState, Exception]:
        if state.should_halt():
            return Success(state)

        t0 = time.time()
        logger.info("=" * 60)
        logger.info("STEP 5. Compare & Analyze")
        logger.info("=" * 60)

        assert ctx.con is not None
        con = ctx.con
        warnings: list[str] = []

        # 1. Z-set field-level diffs (extending Step 4's Z-set tables)
        from src.db_utils import table_exists as _table_exists
        zset_field_results: dict[str, ZSetDiffResult] = {}
        has_new = False

        for cfg in MATCH_CONFIGS:
            if not _table_exists(con, cfg.new_table):
                continue

            has_new = True
            old_ref = TableRef(name=cfg.old_table, key_cols=cfg.key_cols)
            new_ref = TableRef(name=cfg.new_table, key_cols=cfg.key_cols)

            logger.info(f"Comparing {cfg.old_table} vs {cfg.new_table}...")

            # Full Z-set diff with field-level deltas
            zset_result = execute_diff(
                con, old_ref, new_ref,
                cfg.zset_table,
                compare_cols=cfg.compare_cols,
                numeric_cols=cfg.numeric_cols,
            )

            if is_err(zset_result):
                logger.warning(f"Z-set compare failed: {zset_result.failure()}")
                continue

            zset_field_results[cfg.old_table] = zset_result.unwrap()

        # 2. Run existing comparison engine for backwards compatibility
        from src.compare import run as compare_run
        comparisons = compare_run(con)
        ctx.results["comparisons"] = comparisons

        # 3. Discrepancy trend analysis
        trends = _build_discrepancy_detail_zset(con)
        ctx.results["trends"] = trends

        elapsed = time.time() - t0

        # Build summary
        overall_trend = next((t for t in trends if t["trend"] == "overall_mismatch_rate"), None)
        msg_parts = [f"{len(comparisons)} comparison checks"]

        if overall_trend:
            msg_parts.append(
                f"{overall_trend['affected']:,}/{overall_trend['total']:,} "
                f"beneficiaries mismatched ({overall_trend['rate_pct']}%)"
            )
            financial_impacts = [t for t in trends if t["trend"].startswith("financial_impact_")]
            if financial_impacts:
                total_impact = sum(t.get("dollar_impact", 0) for t in financial_impacts)
                msg_parts.append(f"${total_impact:,.2f} total financial divergence")

            # Add Z-set specific info
            for table, zr in zset_field_results.items():
                top_deltas = sorted(
                    [fd for fd in zr.field_deltas if fd.sum_abs_delta],
                    key=lambda fd: fd.sum_abs_delta or 0,
                    reverse=True,
                )[:3]
                if top_deltas:
                    delta_strs = [
                        f"{fd.column}=${fd.sum_abs_delta:,.0f}" for fd in top_deltas
                    ]
                    logger.info(f"  Z-set top deltas ({table}): {', '.join(delta_strs)}")
        elif not has_new:
            msg_parts.append("No new system data — comparison skipped")

        data = {
            "comparison_count": len(comparisons),
            "has_new_data": has_new,
            "trends": trends,
            "zset_field_results": {
                table: zr.to_legacy_dict()
                for table, zr in zset_field_results.items()
            },
        }
        ctx.results["compare"] = data

        msg = ". ".join(msg_parts)
        logger.info(f"  ✓ {msg} ({elapsed:.1f}s)")

        outcome = StepOutcome(
            step_name="compare",
            success=True,
            message=msg,
            data=data,
            errors=(),
            warnings=tuple(warnings),
        )
        return Success(state.with_outcome(outcome))

    return _step


# ===================================================================
# Step 6: Report — Pure Fold + Effectful Write
# ===================================================================

def _build_export_plan(
    con: duckdb.DuckDBPyConnection,
    report_dir: Path,
) -> ReportPlan:
    """Pure: build an export plan from available analysis tables."""
    export_ops: list[ExportOp] = []
    export_dir = report_dir / "exports"

    try:
        tables = [
            row[0] for row in con.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_name LIKE '\\_discrepancy%' ESCAPE '\\' "
                "OR table_name LIKE '\\_match%' ESCAPE '\\' "
                "OR table_name LIKE '\\_financial\\_recon' ESCAPE '\\' "
                "OR table_name LIKE '\\_zset%' ESCAPE '\\'"
            ).fetchall()
        ]
        for t in tables:
            export_ops.append(ExportOp(
                table_name=t,
                csv_path=export_dir / f"{t}.csv",
                parquet_path=export_dir / f"{t}.parquet",
            ))
    except duckdb.Error as e:
        logger.debug(f"Could not list tables for export: {e}")

    return ReportPlan(
        report_dir=report_dir,
        export_ops=tuple(export_ops),
    )


def _execute_export_plan(
    con: duckdb.DuckDBPyConnection,
    plan: ReportPlan,
) -> tuple[list[str], list[str], list[str]]:
    """Effectful: execute the export plan. Returns (csv_paths, parquet_paths, warnings)."""
    csv_exports: list[str] = []
    parquet_exports: list[str] = []
    export_warnings: list[str] = []

    if not plan.export_ops:
        return csv_exports, parquet_exports, export_warnings

    export_dir = plan.report_dir / "exports"
    export_dir.mkdir(exist_ok=True)

    for op in plan.export_ops:
        try:
            con.execute(f"COPY {op.table_name} TO '{op.csv_path}' (HEADER, DELIMITER ',')")
            csv_exports.append(str(op.csv_path))
            con.execute(f"COPY {op.table_name} TO '{op.parquet_path}' (FORMAT PARQUET, COMPRESSION ZSTD)")
            parquet_exports.append(str(op.parquet_path))
            logger.info(f"Exported {op.table_name} → CSV + Parquet")
        except Exception as e:
            export_warnings.append(f"Export failed for {op.table_name}: {e}")

    return csv_exports, parquet_exports, export_warnings


def step6_functional(
    ctx: PipelineContext,
) -> callable:
    """Closure: returns a StepFunction for report generation."""

    def _step(state: PipelineState) -> Result[PipelineState, Exception]:
        if state.should_halt():
            return Success(state)

        t0 = time.time()
        logger.info("=" * 60)
        logger.info("STEP 6. Report")
        logger.info("=" * 60)

        warnings: list[str] = []
        con = ctx.con

        # 1. Pure fold: gather all data for the report
        profiles = ctx.results.get("profiles", {})
        validations = ctx.results.get("validations", [])
        comparisons = ctx.results.get("comparisons", [])

        # 2. Effectful: render the report (delegate to existing report.py)
        from src.report import run as report_run
        try:
            report_path = report_run(
                profiles, validations, comparisons,
                con=con, pipeline_results=ctx.results,
            )
        except Exception as e:
            elapsed = time.time() - t0
            msg = f"Report generation failed: {e}"
            logger.error(f"  ✗ {msg} ({elapsed:.1f}s)")
            outcome = StepOutcome.err("report", msg, (msg,))
            return Success(state.with_outcome(outcome))

        # 3. Pure: build export plan
        plan = _build_export_plan(con, report_path.parent)

        # 4. Effectful: execute export plan
        csv_exports, parquet_exports, export_warnings = (
            _execute_export_plan(con, plan)
        )
        warnings.extend(export_warnings)

        elapsed = time.time() - t0
        data = {
            "report_path": str(report_path),
            "csv_exports": csv_exports,
            "parquet_exports": parquet_exports,
            "export_plan": {
                "operations": len(plan.export_ops),
                "tables": [op.table_name for op in plan.export_ops],
            },
        }
        ctx.results["report"] = data

        msg = (
            f"Report: {report_path}. "
            f"{len(csv_exports)} CSV exports. "
            f"{len(parquet_exports)} Parquet exports."
        )
        logger.info(f"  ✓ {msg} ({elapsed:.1f}s)")

        outcome = StepOutcome(
            step_name="report",
            success=True,
            message=msg,
            data=data,
            errors=(),
            warnings=tuple(warnings),
        )
        return Success(state.with_outcome(outcome))

    return _step


__all__ = [
    "step3_functional",
    "step4_functional",
    "step5_functional",
    "step6_functional",
]
