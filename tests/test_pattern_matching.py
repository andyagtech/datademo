"""
Tests for Python 3.14 pattern matching on monadic types.

Demonstrates that structural pattern matching works correctly
with Result, Maybe, and domain-specific algebraic data types.
"""

from __future__ import annotations

import pytest

from src.functional import Success, Failure, Some, Nothing, PipelineError
from src.pipeline.receive_pure import (
    FileInfo, FileInventory, ReceiveResult, DiscoveredFiles,
)
from src.pipeline.schema_validate_pure import (
    FileType, SchemaValidationResult, FileValidation, ColumnDiff,
)
from src.pattern_matching import (
    describe_result,
    handle_pipeline_error,
    maybe_to_str,
    lookup_file,
    describe_file_type,
    summarize_validation,
    receive_summary,
    Threshold,
)


# ---------------------------------------------------------------------------
# Result pattern matching
# ---------------------------------------------------------------------------

class TestDescribeResult:
    def test_success(self):
        assert describe_result(Success(42)) == "Success: 42"

    def test_failure(self):
        assert describe_result(Failure("oops")) == "Failure: oops"

    def test_success_string(self):
        assert describe_result(Success("hello")) == "Success: hello"


class TestHandlePipelineError:
    def test_success_passthrough(self):
        assert handle_pipeline_error(Success("data loaded")) == "OK: data loaded"

    def test_receive_failure(self):
        err = PipelineError(step="receive", message="files missing")
        result = handle_pipeline_error(Failure(err))
        assert result == "Receive failed: files missing"

    def test_schema_failure(self):
        err = PipelineError(step="schema_validate", message="bad headers")
        result = handle_pipeline_error(Failure(err))
        assert result == "Schema invalid: bad headers"

    def test_failure_with_cause(self):
        cause = FileNotFoundError("data.csv")
        err = PipelineError(step="ingest", message="load failed", cause=cause)
        result = handle_pipeline_error(Failure(err))
        assert "[ingest]" in result
        assert "FileNotFoundError" in result

    def test_generic_pipeline_error(self):
        err = PipelineError(step="compare", message="mismatch")
        result = handle_pipeline_error(Failure(err))
        assert result == "[compare] mismatch"

    def test_unknown_error(self):
        result = handle_pipeline_error(Failure("raw string error"))
        assert "Unknown error" in result


# ---------------------------------------------------------------------------
# Maybe pattern matching
# ---------------------------------------------------------------------------

class TestMaybeToStr:
    def test_some(self):
        assert maybe_to_str(Some(42)) == "42"

    def test_nothing_default(self):
        assert maybe_to_str(Nothing) == "<empty>"

    def test_nothing_custom_default(self):
        assert maybe_to_str(Nothing, default="N/A") == "N/A"


class TestLookupFile:
    def test_found(self):
        inv = FileInventory(files=(
            FileInfo(name="data.csv", path="/data.csv", size_bytes=1048576, sha256="abcdef1234567890" * 4),
        ))
        result = lookup_file(inv, "data.csv")
        assert "Found data.csv" in result
        assert "1.0 MB" in result

    def test_not_found(self):
        inv = FileInventory(files=())
        result = lookup_file(inv, "missing.csv")
        assert "not found" in result


# ---------------------------------------------------------------------------
# FileType as algebraic data type
# ---------------------------------------------------------------------------

class TestDescribeFileType:
    def test_beneficiary(self):
        assert describe_file_type(FileType(kind="beneficiary")) == "Beneficiary Summary"

    def test_carrier(self):
        assert describe_file_type(FileType(kind="carrier_claims")) == "Carrier Claims"

    def test_unknown(self):
        result = describe_file_type(FileType(kind="mystery"))
        assert "Unknown" in result


# ---------------------------------------------------------------------------
# Schema validation matching
# ---------------------------------------------------------------------------

class TestSummarizeValidation:
    def test_failure(self):
        result = summarize_validation(Failure(ValueError("bad")))
        assert "Validation error" in result

    def test_all_valid(self):
        sv = SchemaValidationResult(validations=(
            FileValidation(
                file_name="a.csv", path="/a.csv", valid=True,
                file_type=FileType(kind="beneficiary"),
                headers=("A",), column_diff=ColumnDiff(missing=(), extra=()),
                errors=(), warnings=(), sample_rows=(),
            ),
        ))
        result = summarize_validation(Success(sv))
        assert "1 files valid ✓" in result

    def test_some_invalid(self):
        sv = SchemaValidationResult(validations=(
            FileValidation(
                file_name="good.csv", path="/good.csv", valid=True,
                file_type=FileType(kind="beneficiary"),
                headers=("A",), column_diff=ColumnDiff(missing=(), extra=()),
                errors=(), warnings=(), sample_rows=(),
            ),
            FileValidation(
                file_name="bad.csv", path="/bad.csv", valid=False,
                file_type=FileType(kind="unknown"),
                headers=(), column_diff=ColumnDiff(missing=(), extra=()),
                errors=("no headers",), warnings=(), sample_rows=(),
            ),
        ))
        result = summarize_validation(Success(sv))
        assert "1/2 valid" in result
        assert "bad.csv" in result


# ---------------------------------------------------------------------------
# Receive result matching
# ---------------------------------------------------------------------------

class TestReceiveSummary:
    def test_complete(self):
        recv = ReceiveResult(
            source_dir="/data",
            discovered=DiscoveredFiles(
                beneficiary=("a.csv", "b.csv", "c.csv"),
                carrier_claims=("d.csv", "e.csv"),
            ),
            inventory=FileInventory(files=()),
            missing_categories=(),
        )
        assert receive_summary(Success(recv)) == "All files received ✓"

    def test_incomplete(self):
        recv = ReceiveResult(
            source_dir="/data",
            discovered=DiscoveredFiles(beneficiary=("a.csv",), carrier_claims=()),
            inventory=FileInventory(files=()),
            missing_categories=("carrier_claims: found 0, need 2",),
        )
        result = receive_summary(Success(recv))
        assert "Incomplete" in result
        assert "carrier_claims" in result

    def test_file_not_found(self):
        result = receive_summary(Failure(FileNotFoundError("/missing")))
        assert "Directory missing" in result

    def test_permission_error(self):
        result = receive_summary(Failure(PermissionError("/secret")))
        assert "Permission denied" in result

    def test_unexpected_error(self):
        result = receive_summary(Failure(RuntimeError("boom")))
        assert "RuntimeError" in result


# ---------------------------------------------------------------------------
# Threshold guard clauses
# ---------------------------------------------------------------------------

class TestThreshold:
    def test_ok(self):
        t = Threshold(min_files=3, warn_below=5)
        assert t.check(5) == "OK"
        assert t.check(10) == "OK"

    def test_fail(self):
        t = Threshold(min_files=3, warn_below=5)
        assert t.check(2) == "FAIL"
        assert t.check(0) == "FAIL"

    def test_frozen(self):
        t = Threshold(min_files=3, warn_below=5)
        with pytest.raises(AttributeError):
            t.min_files = 10
