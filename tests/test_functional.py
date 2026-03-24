"""Tests for functional programming utilities and pure pipeline functions."""

import zipfile

import pytest

from src.functional import (
    Result, Success, Failure,
    Maybe, Some, Nothing,
    PipelineError,
    pipe, compose, tap, when, unless,
    try_op, catch_as_result, lazy,
)
from src.pipeline.receive_pure import (
    FileInfo, FileInventory, DiscoveredFiles,
    compute_sha256, inventory_directory, discover_files,
    extract_zip, validate_discovery, receive_step_pure,
)
from src.pipeline.state import (
    StepOutcome, PipelineConfig, PipelineState, compose_pipeline,
)


# ---------------------------------------------------------------------------
# Result[T, E]
# ---------------------------------------------------------------------------

class TestResult:
    def test_success_creation(self):
        r = Success(42)
        assert r.is_ok
        assert not r.is_err
        assert r.unwrap() == 42

    def test_failure_creation(self):
        r = Failure("oops")
        assert r.is_err
        assert not r.is_ok

    def test_map_success(self):
        r = Success(5).map(lambda x: x * 2)
        assert r.unwrap() == 10

    def test_map_failure_passthrough(self):
        r = Failure("err").map(lambda x: x * 2)
        assert r.is_err

    def test_bind_success(self):
        r = Success(5).bind(lambda x: Success(x + 1))
        assert r.unwrap() == 6

    def test_bind_failure_short_circuits(self):
        r = Success(5).bind(lambda x: Failure("fail")).bind(lambda x: Success(x + 100))
        assert r.is_err

    def test_bind_initial_failure(self):
        r = Failure("start").bind(lambda x: Success(x + 1))
        assert r.is_err

    def test_unwrap_or(self):
        assert Success(10).unwrap_or(0) == 10
        assert Failure("err").unwrap_or(0) == 0

    def test_unwrap_or_else(self):
        assert Success(10).unwrap_or_else(lambda e: -1) == 10
        assert Failure("err").unwrap_or_else(lambda e: -1) == -1

    def test_unwrap_failure_raises(self):
        with pytest.raises(ValueError):
            Failure("oops").unwrap()

    def test_expect_failure_raises_custom_msg(self):
        with pytest.raises(ValueError, match="custom"):
            Failure("oops").expect("custom")

    def test_map_err(self):
        r = Failure("lower").map_err(lambda e: e.upper())
        assert r._error == "LOWER"

    def test_map_err_passthrough_success(self):
        r = Success(42).map_err(lambda e: e.upper())
        assert r.unwrap() == 42

    def test_to_optional(self):
        assert Success(42).to_optional() == 42
        assert Failure("err").to_optional() is None

    def test_from_exception_success(self):
        r = Result.from_exception(lambda: 42)
        assert r.unwrap() == 42

    def test_from_exception_failure(self):
        r = Result.from_exception(lambda: 1 / 0)
        assert r.is_err
        assert isinstance(r._error, ZeroDivisionError)

    def test_chained_operations(self):
        result = (
            Success(10)
            .map(lambda x: x * 2)
            .bind(lambda x: Success(x + 5) if x > 15 else Failure("too small"))
            .map(lambda x: x * 3)
        )
        assert result.unwrap() == 75  # (10*2=20, 20+5=25, 25*3=75)

    def test_chained_short_circuit(self):
        result = (
            Success(3)
            .map(lambda x: x * 2)
            .bind(lambda x: Success(x + 5) if x > 15 else Failure("too small"))
            .map(lambda x: x * 3)
        )
        assert result.is_err


# ---------------------------------------------------------------------------
# Maybe[T]
# ---------------------------------------------------------------------------

class TestMaybe:
    def test_some_creation(self):
        m = Some(42)
        assert m.is_some
        assert not m.is_nothing
        assert m.unwrap() == 42

    def test_nothing_creation(self):
        m = Nothing()
        assert m.is_nothing
        assert not m.is_some

    def test_map_some(self):
        assert Some(5).map(lambda x: x * 3).unwrap() == 15

    def test_map_nothing(self):
        assert Nothing().map(lambda x: x * 3).is_nothing

    def test_bind_some(self):
        assert Some(5).bind(lambda x: Some(x + 1)).unwrap() == 6

    def test_bind_nothing(self):
        assert Nothing().bind(lambda x: Some(x + 1)).is_nothing

    def test_filter_keeps(self):
        assert Some(10).filter(lambda x: x > 5).unwrap() == 10

    def test_filter_removes(self):
        assert Some(3).filter(lambda x: x > 5).is_nothing

    def test_unwrap_or(self):
        assert Some(10).unwrap_or(0) == 10
        assert Nothing().unwrap_or(0) == 0

    def test_unwrap_nothing_raises(self):
        with pytest.raises(ValueError):
            Nothing().unwrap()

    def test_from_optional_value(self):
        assert Maybe.from_optional(42).unwrap() == 42

    def test_from_optional_none(self):
        assert Maybe.from_optional(None).is_nothing

    def test_to_result(self):
        assert Some(42).to_result("err").unwrap() == 42
        assert Nothing().to_result("err").is_err


# ---------------------------------------------------------------------------
# Functional Composition
# ---------------------------------------------------------------------------

class TestComposition:
    def test_pipe(self):
        result = pipe(5, lambda x: x * 2, lambda x: x + 1)
        assert result == 11

    def test_pipe_single(self):
        assert pipe(5, lambda x: x * 2) == 10

    def test_pipe_no_functions(self):
        assert pipe(5) == 5

    def test_compose(self):
        def add_one(x): return x + 1
        def double(x): return x * 2
        composed = compose(add_one, double)  # add_one(double(x))
        assert composed(5) == 11

    def test_tap_returns_original(self):
        captured = []
        result = pipe(42, tap(lambda x: captured.append(x)), lambda x: x * 2)
        assert result == 84
        assert captured == [42]

    def test_when_true(self):
        transform = when(lambda x: x > 5, lambda x: x * 2)
        assert transform(10) == 20

    def test_when_false(self):
        transform = when(lambda x: x > 5, lambda x: x * 2)
        assert transform(3) == 3

    def test_unless_true(self):
        transform = unless(lambda x: x > 5, lambda x: x * 2)
        assert transform(10) == 10

    def test_unless_false(self):
        transform = unless(lambda x: x > 5, lambda x: x * 2)
        assert transform(3) == 6


# ---------------------------------------------------------------------------
# Error Handling Utilities
# ---------------------------------------------------------------------------

class TestErrorHandling:
    def test_try_op_success(self):
        r = try_op(lambda: 42)
        assert r.unwrap() == 42

    def test_try_op_failure(self):
        r = try_op(lambda: 1 / 0)
        assert r.is_err

    def test_pipeline_error_str(self):
        err = PipelineError(step="ingest", message="file not found")
        assert "[ingest]" in str(err)
        assert "file not found" in str(err)

    def test_pipeline_error_with_cause(self):
        cause = FileNotFoundError("data.csv")
        err = PipelineError(step="receive", message="missing", cause=cause)
        assert "caused by" in str(err)

    def test_catch_as_result_decorator(self):
        @catch_as_result("test_step")
        def divide(a, b):
            return a / b

        assert divide(10, 2).unwrap() == 5.0
        result = divide(10, 0)
        assert result.is_err
        assert result._error.step == "test_step"

    def test_lazy_evaluation(self):
        call_count = 0
        def expensive():
            nonlocal call_count
            call_count += 1
            return 42

        lazy_val = lazy(expensive)
        assert call_count == 0  # Not called yet
        assert lazy_val() == 42
        assert call_count == 1
        assert lazy_val() == 42  # Cached
        assert call_count == 1  # Still 1


# ---------------------------------------------------------------------------
# Pure File Operations (receive_pure.py)
# ---------------------------------------------------------------------------

@pytest.fixture
def csv_dir(tmp_path):
    """Create temp dir with sample CSV files matching CMS naming."""
    d = tmp_path / "old_system"
    d.mkdir()

    for year in [2008, 2009, 2010]:
        p = d / f"DE1_0_{year}_Beneficiary_Summary_File_Sample_1.csv"
        p.write_text("DESYNPUF_ID,BENE_BIRTH_DT\nA,19400101\n")

    for suffix in ["1A", "1B"]:
        p = d / f"DE1_0_2008_to_2010_Carrier_Claims_Sample_{suffix}.csv"
        p.write_text("CLM_ID,DESYNPUF_ID\n001,A\n")

    return d


class TestFileInfo:
    def test_immutable(self):
        fi = FileInfo(name="test.csv", path="/tmp/test.csv", size_bytes=1024, sha256="abc")
        with pytest.raises(AttributeError):
            fi.name = "other.csv"

    def test_size_mb(self):
        fi = FileInfo(name="test.csv", path="/tmp/test.csv", size_bytes=1048576, sha256="abc")
        assert fi.size_mb == 1.0

    def test_to_dict(self):
        fi = FileInfo(name="test.csv", path="/tmp/test.csv", size_bytes=1024, sha256="abc")
        d = fi.to_dict()
        assert d["path"] == "/tmp/test.csv"
        assert d["size_bytes"] == 1024
        assert d["sha256"] == "abc"


class TestFileInventory:
    def test_get_existing(self):
        inv = FileInventory(files=(
            FileInfo(name="a.csv", path="/a.csv", size_bytes=100, sha256="aaa"),
        ))
        assert inv.get("a.csv").is_some

    def test_get_missing(self):
        inv = FileInventory(files=())
        assert inv.get("missing.csv").is_nothing

    def test_to_dict(self):
        inv = FileInventory(files=(
            FileInfo(name="a.csv", path="/a.csv", size_bytes=100, sha256="aaa"),
        ))
        d = inv.to_dict()
        assert "a.csv" in d


class TestDiscoverFiles:
    def test_discover_csv_files(self, csv_dir):
        discovered = discover_files(csv_dir)
        assert len(discovered.beneficiary) == 3
        assert len(discovered.carrier_claims) == 2

    def test_discover_empty_dir(self, tmp_path):
        d = tmp_path / "empty"
        d.mkdir()
        discovered = discover_files(d)
        assert len(discovered.beneficiary) == 0
        assert len(discovered.carrier_claims) == 0

    def test_all_files(self, csv_dir):
        discovered = discover_files(csv_dir)
        assert len(discovered.all_files) == 5


class TestComputeSha256:
    def test_deterministic(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("hello world")
        r1 = compute_sha256(f)
        r2 = compute_sha256(f)
        assert r1.unwrap() == r2.unwrap()
        assert len(r1.unwrap()) == 64

    def test_nonexistent_file(self, tmp_path):
        r = compute_sha256(tmp_path / "nope.txt")
        assert r.is_err


class TestInventoryDirectory:
    def test_inventory_csvs(self, csv_dir):
        result = inventory_directory(csv_dir)
        assert result.is_ok
        inv = result.unwrap()
        assert len(inv.files) == 5

    def test_inventory_empty_dir(self, tmp_path):
        d = tmp_path / "empty"
        d.mkdir()
        result = inventory_directory(d)
        assert result.is_ok
        assert len(result.unwrap().files) == 0


class TestExtractZip:
    def test_extract_zip(self, tmp_path):
        csv_path = tmp_path / "data.csv"
        csv_path.write_text("a,b\n1,2\n")
        zip_path = tmp_path / "archive.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.write(csv_path, "data.csv")

        dest = tmp_path / "extracted"
        result = extract_zip(zip_path, dest)
        assert result.is_ok
        assert (dest / "data.csv").exists()

    def test_extract_bad_zip(self, tmp_path):
        bad_zip = tmp_path / "bad.zip"
        bad_zip.write_text("not a zip")
        result = extract_zip(bad_zip, tmp_path / "dest")
        assert result.is_err


class TestValidateDiscovery:
    def test_valid(self):
        d = DiscoveredFiles(
            beneficiary=("a.csv", "b.csv", "c.csv"),
            carrier_claims=("d.csv", "e.csv"),
        )
        is_valid, missing = validate_discovery(d)
        assert is_valid
        assert missing == ()

    def test_missing_beneficiary(self):
        d = DiscoveredFiles(
            beneficiary=("a.csv",),
            carrier_claims=("d.csv", "e.csv"),
        )
        is_valid, missing = validate_discovery(d)
        assert not is_valid
        assert any("beneficiary" in m for m in missing)

    def test_custom_thresholds(self):
        d = DiscoveredFiles(
            beneficiary=("a.csv",),
            carrier_claims=("d.csv",),
        )
        is_valid, _ = validate_discovery(d, expected_beneficiary=1, expected_carrier=1)
        assert is_valid


class TestReceiveStepPure:
    def test_receive_complete(self, csv_dir):
        result = receive_step_pure(csv_dir.parent, old_system_subdir="old_system")
        assert result.is_ok
        recv = result.unwrap()
        assert recv.is_complete
        assert len(recv.discovered.beneficiary) == 3
        assert len(recv.inventory.files) == 5

    def test_receive_incomplete(self, tmp_path):
        d = tmp_path / "old_system"
        d.mkdir()
        (d / "DE1_0_2008_Beneficiary_Summary_File_Sample_1.csv").write_text("a\n1\n")
        result = receive_step_pure(tmp_path, old_system_subdir="old_system")
        assert result.is_ok
        recv = result.unwrap()
        assert not recv.is_complete
        assert len(recv.missing_categories) > 0

    def test_legacy_dict_format(self, csv_dir):
        result = receive_step_pure(csv_dir.parent, old_system_subdir="old_system")
        legacy = result.unwrap().to_legacy_dict()
        assert "source_dir" in legacy
        assert "discovered" in legacy
        assert "inventory" in legacy
        assert legacy["complete"] is True


# ---------------------------------------------------------------------------
# Immutable Pipeline State (state.py)
# ---------------------------------------------------------------------------

class TestStepOutcome:
    def test_ok_factory(self):
        o = StepOutcome.ok("receive", "Received 5 files")
        assert o.success
        assert o.step_name == "receive"
        assert o.errors == ()

    def test_err_factory(self):
        o = StepOutcome.err("schema", "Failed", ("missing cols",))
        assert not o.success
        assert o.errors == ("missing cols",)

    def test_add_warning_immutable(self):
        o = StepOutcome.ok("receive", "ok")
        o2 = o.add_warning("watch out")
        assert o.warnings == ()  # Original unchanged
        assert o2.warnings == ("watch out",)

    def test_frozen(self):
        o = StepOutcome.ok("receive", "ok")
        with pytest.raises(AttributeError):
            o.success = False


class TestPipelineConfig:
    def test_frozen(self, tmp_path):
        config = PipelineConfig(old_data_dir=tmp_path)
        with pytest.raises(AttributeError):
            config.mode = "cloud"

    def test_defaults(self, tmp_path):
        config = PipelineConfig(old_data_dir=tmp_path)
        assert config.skip_ingest is False
        assert config.mode == "local"
        assert config.new_data_dir.is_nothing


class TestPipelineState:
    def test_initial_state(self, tmp_path):
        config = PipelineConfig(old_data_dir=tmp_path)
        state = PipelineState(config=config)
        assert state.outcomes == ()
        assert not state.halted
        assert state.success_count == 0

    def test_with_outcome_immutable(self, tmp_path):
        config = PipelineConfig(old_data_dir=tmp_path)
        s0 = PipelineState(config=config)
        s1 = s0.with_outcome(StepOutcome.ok("receive", "ok"))

        # Original unchanged
        assert len(s0.outcomes) == 0
        assert len(s1.outcomes) == 1
        assert s1.success_count == 1

    def test_auto_halt_on_failure(self, tmp_path):
        config = PipelineConfig(old_data_dir=tmp_path)
        state = PipelineState(config=config)
        state = state.with_outcome(StepOutcome.ok("receive", "ok"))
        assert not state.halted

        state = state.with_outcome(StepOutcome.err("schema", "bad", ("err",)))
        assert state.halted
        assert state.halt_reason == "bad"

    def test_get_step_outcome(self, tmp_path):
        config = PipelineConfig(old_data_dir=tmp_path)
        state = PipelineState(config=config)
        state = state.with_outcome(StepOutcome.ok("receive", "ok"))
        state = state.with_outcome(StepOutcome.ok("schema", "valid"))

        assert state.get_step_outcome("receive").unwrap().success
        assert state.get_step_outcome("schema").unwrap().success
        assert state.get_step_outcome("ingest").is_nothing

    def test_all_succeeded(self, tmp_path):
        config = PipelineConfig(old_data_dir=tmp_path)
        state = PipelineState(config=config)
        state = state.with_outcome(StepOutcome.ok("a", "ok"))
        state = state.with_outcome(StepOutcome.ok("b", "ok"))
        assert state.all_succeeded

    def test_compose_pipeline(self, tmp_path):
        config = PipelineConfig(old_data_dir=tmp_path)
        initial = PipelineState(config=config)

        def step_a(state):
            return Success(state.with_outcome(StepOutcome.ok("a", "done")))

        def step_b(state):
            return Success(state.with_outcome(StepOutcome.ok("b", "done")))

        pipeline = compose_pipeline(step_a, step_b)
        result = pipeline(initial)
        assert result.is_ok
        final = result.unwrap()
        assert final.total_count == 2
        assert final.all_succeeded

    def test_compose_pipeline_halts_on_failure(self, tmp_path):
        config = PipelineConfig(old_data_dir=tmp_path)
        initial = PipelineState(config=config)

        def step_a(state):
            return Success(
                state.with_outcome(StepOutcome.err("a", "fail", ("boom",)))
            )

        def step_b(state):
            return Success(state.with_outcome(StepOutcome.ok("b", "done")))

        pipeline = compose_pipeline(step_a, step_b)
        result = pipeline(initial)
        assert result.is_ok
        final = result.unwrap()
        assert final.total_count == 1  # step_b never ran
        assert final.halted
