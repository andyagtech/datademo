"""
Pipeline Runner — Orchestrates the 6-step pipeline with gate logic.

Supports both local execution and (future) cloud execution via adapters.
"""

import logging
import time
from pathlib import Path

from src.pipeline import PipelineContext, StepResult
from src.pipeline.step1_receive import run as step1_run
from src.pipeline.step2_schema_validate import run as step2_run
from src.pipeline.step3_ingest import run as step3_run
from src.pipeline.step4_match import run as step4_run
from src.pipeline.step5_compare import run as step5_run
from src.pipeline.step6_report import run as step6_run

logger = logging.getLogger("pipeline")

STEPS = [
    ("1. Receive & Verify", step1_run),
    ("2. Schema Validation", step2_run),
    ("3. Ingest & Profile", step3_run),
    ("4. Record Matching", step4_run),
    ("5. Compare & Analyze", step5_run),
    ("6. Report", step6_run),
]


def run_pipeline(ctx: PipelineContext) -> list[StepResult]:
    """Execute all pipeline steps sequentially with gate logic."""
    results = []
    t_start = time.time()

    for step_name, step_fn in STEPS:
        if ctx.halted:
            logger.error(f"Pipeline halted before {step_name}: {ctx.halt_reason}")
            break

        logger.info("=" * 60)
        logger.info(f"STEP {step_name}")
        logger.info("=" * 60)

        t_step = time.time()
        result = step_fn(ctx)
        elapsed = time.time() - t_step

        results.append(result)

        status = "✓" if result.success else "✗"
        logger.info(f"  {status} {result.message} ({elapsed:.1f}s)")

        for w in result.warnings:
            logger.warning(f"  ⚠ {w}")
        for e in result.errors:
            logger.error(f"  ✗ {e}")

        if not result.success:
            logger.error(f"Step {step_name} failed. Pipeline halted.")
            ctx.halted = True
            ctx.halt_reason = result.message
            break

    elapsed = time.time() - t_start
    logger.info("=" * 60)

    completed = sum(1 for r in results if r.success)
    total = len(STEPS)
    logger.info(f"Pipeline: {completed}/{total} steps completed in {elapsed:.1f}s")

    if ctx.halted:
        logger.error(f"Halted: {ctx.halt_reason}")
    else:
        report_data = ctx.results.get("report", {})
        if "report_path" in report_data:
            logger.info(f"Report: {report_data['report_path']}")

    logger.info("=" * 60)
    return results
