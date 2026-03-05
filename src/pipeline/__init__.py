"""
CMS Claims Comparison Pipeline — 6-Step Architecture

Steps:
  1. RECEIVE         — Accept files, verify integrity, extract zips
  2. SCHEMA VALIDATE — Gate check on headers, types, expected files
  3. INGEST & PROFILE — Load into DuckDB, profile data quality
  4. MATCH & VALIDATE — Record matching by key + internal consistency checks
  5. COMPARE         — Field-level diffs, discrepancy classification, trend analysis
  6. REPORT          — Generate HTML report with findings

Each step exposes:
  run(ctx: PipelineContext) -> StepResult
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import duckdb

from src.adapters import StorageAdapter


@dataclass
class PipelineContext:
    """Shared state passed between pipeline steps."""

    # Paths
    old_data_dir: Path
    new_data_dir: Path | None = None
    db_path: Path | None = None

    # Storage adapter (local filesystem or S3)
    storage: StorageAdapter | None = None

    # Runtime
    con: duckdb.DuckDBPyConnection | None = None
    skip_ingest: bool = False

    # Execution mode
    mode: str = "local"  # "local" or "cloud"

    # Accumulated results from each step.
    # Convention: each step writes its own key ("receive", "schema_validate",
    # "ingest", "match", "compare", "report").  Steps 3-5 also write shared
    # cross-step keys ("profiles", "anomalies", "validations", "comparisons",
    # "trends") consumed by the report step.
    results: dict[str, Any] = field(default_factory=dict)

    # Gate flags — a step can halt the pipeline
    halted: bool = False
    halt_reason: str = ""


@dataclass
class StepResult:
    """Outcome of a single pipeline step."""

    step_name: str
    success: bool
    message: str
    data: dict = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
