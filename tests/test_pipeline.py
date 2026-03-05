"""Tests for the 6-step pipeline architecture."""

import csv
import zipfile
from pathlib import Path

import pytest
import duckdb

from src.pipeline import PipelineContext, StepResult
from src.pipeline.step1_receive import run as step1_run, _sha256, _extract_zip
from src.pipeline.step2_schema_validate import (
    run as step2_run, validate_file, _classify_file, _read_csv_headers,
    BENEFICIARY_EXPECTED_COLS, CARRIER_EXPECTED_COLS,
)
from src.pipeline.step4_match import _build_match_table


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def data_dir(tmp_path):
    """Create a temporary data directory with sample CSV files."""
    raw = tmp_path / "old_system"
    raw.mkdir()

    # Beneficiary summary CSV (2008)
    bene_headers = sorted(BENEFICIARY_EXPECTED_COLS)
    bene_path = raw / "DE1_0_2008_Beneficiary_Summary_File_Sample_1.csv"
    with open(bene_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(bene_headers)
        w.writerow(["BENE_A"] + ["0"] * (len(bene_headers) - 1))

    # Carrier claims CSV
    carrier_headers = sorted(CARRIER_EXPECTED_COLS)
    carrier_path = raw / "DE1_0_2008_to_2010_Carrier_Claims_Sample_1A.csv"
    with open(carrier_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(carrier_headers)
        w.writerow(["CLM_001"] + ["0"] * (len(carrier_headers) - 1))

    return tmp_path


@pytest.fixture
def new_data_dir(tmp_path):
    """Create a temporary new-system data directory."""
    new_dir = tmp_path / "new_system"
    new_dir.mkdir()

    bene_headers = sorted(BENEFICIARY_EXPECTED_COLS)
    bene_path = new_dir / "New_Beneficiary_Summary.csv"
    with open(bene_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(bene_headers)
        w.writerow(["BENE_A"] + ["0"] * (len(bene_headers) - 1))

    carrier_headers = sorted(CARRIER_EXPECTED_COLS)
    carrier_path = new_dir / "New_Carrier_Claims.csv"
    with open(carrier_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(carrier_headers)
        w.writerow(["CLM_001"] + ["0"] * (len(carrier_headers) - 1))

    return new_dir


# ---------------------------------------------------------------------------
# Step 1: Receive
# ---------------------------------------------------------------------------

class TestStep1Receive:
    def test_sha256_deterministic(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("hello")
        h1 = _sha256(f)
        h2 = _sha256(f)
        assert h1 == h2
        assert len(h1) == 64

    def test_extract_zip(self, tmp_path):
        # Create a zip
        csv_path = tmp_path / "test.csv"
        csv_path.write_text("a,b\n1,2\n")
        zip_path = tmp_path / "test.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.write(csv_path, "test.csv")

        dest = tmp_path / "extracted"
        extracted = _extract_zip(zip_path, dest)
        assert len(extracted) == 1
        assert (dest / "test.csv").exists()

    def test_receive_old_system(self, data_dir):
        ctx = PipelineContext(old_data_dir=data_dir)
        result = step1_run(ctx)
        # Won't be "complete" since we only have 2 of 5 expected files,
        # but it should run without crashing
        assert result.step_name == "receive"
        assert "old_system" in ctx.results["receive"]

    def test_receive_with_new_data(self, data_dir, new_data_dir):
        ctx = PipelineContext(old_data_dir=data_dir, new_data_dir=new_data_dir)
        result = step1_run(ctx)
        assert ctx.results["receive"]["new_system"] is not None
        assert ctx.results["receive"]["new_system"]["has_beneficiary"] is True
        assert ctx.results["receive"]["new_system"]["has_claims"] is True

    def test_receive_no_new_data(self, data_dir):
        ctx = PipelineContext(old_data_dir=data_dir)
        result = step1_run(ctx)
        assert ctx.results["receive"]["new_system"] is None


# ---------------------------------------------------------------------------
# Step 2: Schema Validation
# ---------------------------------------------------------------------------

class TestStep2SchemaValidate:
    def test_classify_beneficiary_file(self):
        headers = list(BENEFICIARY_EXPECTED_COLS)
        assert _classify_file(headers) == "beneficiary"

    def test_classify_carrier_file(self):
        headers = list(CARRIER_EXPECTED_COLS)
        assert _classify_file(headers) == "carrier_claims"

    def test_classify_unknown_file(self):
        assert _classify_file(["foo", "bar", "baz"]) is None

    def test_validate_beneficiary_csv(self, data_dir):
        csv_path = data_dir / "old_system" / "DE1_0_2008_Beneficiary_Summary_File_Sample_1.csv"
        result = validate_file(csv_path)
        assert result["valid"] is True
        assert result["file_type"] == "beneficiary"
        assert result["header_count"] == len(BENEFICIARY_EXPECTED_COLS)

    def test_validate_carrier_csv(self, data_dir):
        csv_path = data_dir / "old_system" / "DE1_0_2008_to_2010_Carrier_Claims_Sample_1A.csv"
        result = validate_file(csv_path)
        assert result["valid"] is True
        assert result["file_type"] == "carrier_claims"

    def test_schema_validation_step(self, data_dir):
        ctx = PipelineContext(old_data_dir=data_dir)
        # Run step 1 first to populate receive results
        step1_run(ctx)
        result = step2_run(ctx)
        assert result.step_name == "schema_validate"
        assert result.success is True
        assert ctx.results["schema_validate"]["beneficiary_files"] >= 1
        assert ctx.results["schema_validate"]["carrier_files"] >= 1

    def test_read_csv_headers(self, data_dir):
        csv_path = data_dir / "old_system" / "DE1_0_2008_Beneficiary_Summary_File_Sample_1.csv"
        headers = _read_csv_headers(csv_path)
        assert len(headers) == len(BENEFICIARY_EXPECTED_COLS)


# ---------------------------------------------------------------------------
# Step 4: Record Matching
# ---------------------------------------------------------------------------

class TestStep4Match:
    def test_build_match_table_all_matched(self):
        con = duckdb.connect(":memory:")
        con.execute("CREATE TABLE old_t AS SELECT 'A' AS id, 1 AS val")
        con.execute("CREATE TABLE new_t AS SELECT 'A' AS id, 1 AS val")
        result = _build_match_table(con, "old_t", "new_t", ["id"], "_match_test")
        assert result["matched"] == 1
        assert result["old_only"] == 0
        assert result["new_only"] == 0

    def test_build_match_table_old_only(self):
        con = duckdb.connect(":memory:")
        con.execute("CREATE TABLE old_t AS SELECT * FROM (VALUES ('A', 1), ('B', 2)) AS t(id, val)")
        con.execute("CREATE TABLE new_t AS SELECT 'A' AS id, 1 AS val")
        result = _build_match_table(con, "old_t", "new_t", ["id"], "_match_test")
        assert result["matched"] == 1
        assert result["old_only"] == 1

    def test_build_match_table_new_only(self):
        con = duckdb.connect(":memory:")
        con.execute("CREATE TABLE old_t AS SELECT 'A' AS id, 1 AS val")
        con.execute("CREATE TABLE new_t AS SELECT * FROM (VALUES ('A', 1), ('C', 3)) AS t(id, val)")
        result = _build_match_table(con, "old_t", "new_t", ["id"], "_match_test")
        assert result["matched"] == 1
        assert result["new_only"] == 1

    def test_build_match_table_composite_key(self):
        con = duckdb.connect(":memory:")
        con.execute("""
            CREATE TABLE old_t AS SELECT * FROM (VALUES
                ('A', 2008, 100), ('A', 2009, 110)
            ) AS t(id, yr, val)
        """)
        con.execute("""
            CREATE TABLE new_t AS SELECT * FROM (VALUES
                ('A', 2008, 105), ('A', 2009, 110), ('A', 2010, 120)
            ) AS t(id, yr, val)
        """)
        result = _build_match_table(con, "old_t", "new_t", ["id", "yr"], "_match_test")
        assert result["matched"] == 2
        assert result["old_only"] == 0
        assert result["new_only"] == 1

    def test_match_rate_calculation(self):
        con = duckdb.connect(":memory:")
        con.execute("CREATE TABLE old_t AS SELECT * FROM (VALUES ('A'), ('B'), ('C'), ('D')) AS t(id)")
        con.execute("CREATE TABLE new_t AS SELECT * FROM (VALUES ('A'), ('B'), ('E')) AS t(id)")
        result = _build_match_table(con, "old_t", "new_t", ["id"], "_match_test")
        assert result["matched"] == 2
        assert result["old_only"] == 2
        assert result["new_only"] == 1
        assert result["match_rate"] == 40.0  # 2 matched out of 5 total


# ---------------------------------------------------------------------------
# Pipeline Context & StepResult
# ---------------------------------------------------------------------------

class TestPipelineContext:
    def test_context_defaults(self, tmp_path):
        ctx = PipelineContext(old_data_dir=tmp_path)
        assert ctx.halted is False
        assert ctx.results == {}
        assert ctx.con is None

    def test_context_halt(self, tmp_path):
        ctx = PipelineContext(old_data_dir=tmp_path)
        ctx.halted = True
        ctx.halt_reason = "test failure"
        assert ctx.halted is True

    def test_step_result(self):
        r = StepResult(step_name="test", success=True, message="ok")
        assert r.success
        assert r.errors == []
        assert r.warnings == []
