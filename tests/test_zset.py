"""
Tests for Z-Set Algebra and Query Algebra

Verifies algebraic properties of Z-sets and the interpreter pattern
for pure query descriptions.
"""

from __future__ import annotations

import duckdb
import pytest

from src.functional import is_ok, is_err
from src.zset import (
    TableRef, ZSetStats, FieldDelta,
    diff_sql, field_diff_sql, stats_sql,
    execute_diff, table_to_ref,
)
from src.pipeline.query_algebra import (
    IngestOp, IngestPlan, AnomalyCheck, AnomalyResult,
    ValidationRule, ValidationOutcome, MatchConfig,
    ANOMALY_CHECKS, MATCH_CONFIGS,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def con():
    """In-memory DuckDB connection with test data."""
    c = duckdb.connect(":memory:")
    # Old system
    c.execute("""
        CREATE TABLE old_t (id INT, name VARCHAR, amount DOUBLE);
        INSERT INTO old_t VALUES (1, 'Alice', 100.0);
        INSERT INTO old_t VALUES (2, 'Bob', 200.0);
        INSERT INTO old_t VALUES (3, 'Carol', 300.0);
    """)
    # New system (Alice unchanged, Bob modified, Carol deleted, Dave added)
    c.execute("""
        CREATE TABLE new_t (id INT, name VARCHAR, amount DOUBLE);
        INSERT INTO new_t VALUES (1, 'Alice', 100.0);
        INSERT INTO new_t VALUES (2, 'Bob', 250.0);
        INSERT INTO new_t VALUES (4, 'Dave', 400.0);
    """)
    yield c
    c.close()


@pytest.fixture
def old_ref():
    return TableRef(name="old_t", key_cols=("id",), value_cols=("name", "amount"))


@pytest.fixture
def new_ref():
    return TableRef(name="new_t", key_cols=("id",), value_cols=("name", "amount"))


# ---------------------------------------------------------------------------
# TableRef tests
# ---------------------------------------------------------------------------

class TestTableRef:
    def test_frozen(self, old_ref):
        with pytest.raises(AttributeError):
            old_ref.name = "changed"

    def test_all_cols(self, old_ref):
        assert old_ref.all_cols == ("id", "name", "amount")

    def test_table_to_ref(self, con):
        result = table_to_ref(con, "old_t", ("id",))
        assert is_ok(result)
        ref = result.unwrap()
        assert ref.name == "old_t"
        assert ref.key_cols == ("id",)
        assert "name" in ref.value_cols
        assert "amount" in ref.value_cols

    def test_table_to_ref_missing(self, con):
        result = table_to_ref(con, "nonexistent", ("id",))
        assert is_err(result)


# ---------------------------------------------------------------------------
# Pure SQL generation tests (no DB needed)
# ---------------------------------------------------------------------------

class TestPureSqlGeneration:
    def test_diff_sql_contains_full_outer_join(self, old_ref, new_ref):
        sql = diff_sql(old_ref, new_ref, "_zset_test")
        assert "FULL OUTER JOIN" in sql
        assert "_weight" in sql
        assert "_status" in sql

    def test_diff_sql_contains_table_names(self, old_ref, new_ref):
        sql = diff_sql(old_ref, new_ref, "_zset_test")
        assert "old_t" in sql
        assert "new_t" in sql

    def test_stats_sql_counts_weights(self):
        sql = stats_sql("_zset_test")
        assert "insertions" in sql
        assert "deletions" in sql
        assert "unchanged" in sql

    def test_field_diff_sql_non_numeric(self, old_ref, new_ref):
        sql = field_diff_sql(old_ref, new_ref, ("name",), is_numeric=False)
        assert "mismatch_name" in sql
        assert "INNER JOIN" in sql

    def test_field_diff_sql_numeric(self, old_ref, new_ref):
        sql = field_diff_sql(old_ref, new_ref, ("amount",), is_numeric=True)
        assert "mismatch_amount" in sql
        assert "delta_sum_amount" in sql
        assert "delta_avg_amount" in sql
        assert "delta_max_amount" in sql


# ---------------------------------------------------------------------------
# Z-set diff execution tests (uses DB)
# ---------------------------------------------------------------------------

class TestExecuteDiff:
    def test_basic_diff(self, con, old_ref, new_ref):
        result = execute_diff(con, old_ref, new_ref, "_zset_test")
        assert is_ok(result)
        zr = result.unwrap()

        assert zr.stats.total_rows == 4  # Alice + Bob + Carol + Dave
        assert zr.stats.unchanged == 2   # Alice + Bob (matched by key)
        assert zr.stats.deletions == 1   # Carol (old only)
        assert zr.stats.insertions == 1  # Dave (new only)

    def test_diff_field_deltas(self, con, old_ref, new_ref):
        result = execute_diff(
            con, old_ref, new_ref, "_zset_test",
            compare_cols=("name",),
            numeric_cols=("amount",),
        )
        assert is_ok(result)
        zr = result.unwrap()

        # Find the 'name' delta
        name_delta = next(fd for fd in zr.field_deltas if fd.column == "name")
        assert name_delta.mismatches == 0  # Both Alice and Bob have same name
        assert name_delta.total_matched == 2

        # Find the 'amount' delta
        amt_delta = next(fd for fd in zr.field_deltas if fd.column == "amount")
        assert amt_delta.mismatches == 1  # Bob: 200→250
        assert amt_delta.sum_abs_delta == 50.0  # |200 - 250| = 50

    def test_diff_creates_table(self, con, old_ref, new_ref):
        execute_diff(con, old_ref, new_ref, "_zset_test")
        rows = con.execute("SELECT * FROM _zset_test ORDER BY id").fetchall()
        assert len(rows) == 4

    def test_zset_view_properties(self, con, old_ref, new_ref):
        result = execute_diff(con, old_ref, new_ref, "_zset_test")
        zr = result.unwrap()
        zset = zr.zset

        # Insertions (Dave)
        ins = con.execute(zset.insertions_sql).fetchall()
        assert len(ins) == 1

        # Deletions (Carol)
        dels = con.execute(zset.deletions_sql).fetchall()
        assert len(dels) == 1

        # Changes (Carol + Dave)
        changes = con.execute(zset.changes_sql).fetchall()
        assert len(changes) == 2

    def test_to_legacy_dict(self, con, old_ref, new_ref):
        result = execute_diff(con, old_ref, new_ref, "_zset_test")
        d = result.unwrap().to_legacy_dict()
        assert d["old_table"] == "old_t"
        assert d["new_table"] == "new_t"
        assert d["matched"] == 2
        assert d["old_only"] == 1
        assert d["new_only"] == 1
        assert d["match_rate"] == 50.0


# ---------------------------------------------------------------------------
# Z-set algebraic properties
# ---------------------------------------------------------------------------

class TestZSetAlgebraicProperties:
    """Verify Z-set group properties using DuckDB."""

    def test_identity_diff_is_empty(self, con):
        """A - A = ∅ (self-diff has no changes)."""
        ref = TableRef(name="old_t", key_cols=("id",))
        result = execute_diff(con, ref, ref, "_zset_identity")
        zr = result.unwrap()
        assert zr.stats.insertions == 0
        assert zr.stats.deletions == 0
        assert zr.stats.unchanged == 3  # all matched

    def test_empty_new_is_all_deletions(self, con):
        """A - ∅ = A (everything is a deletion)."""
        con.execute("CREATE TABLE empty_t (id INT, name VARCHAR, amount DOUBLE)")
        old = TableRef(name="old_t", key_cols=("id",))
        new = TableRef(name="empty_t", key_cols=("id",))
        result = execute_diff(con, old, new, "_zset_empty")
        zr = result.unwrap()
        assert zr.stats.deletions == 3
        assert zr.stats.insertions == 0

    def test_empty_old_is_all_insertions(self, con):
        """∅ - A is impossible in our model, but A - ∅ shows ∅ has no rows."""
        con.execute("CREATE TABLE empty_t2 (id INT, name VARCHAR, amount DOUBLE)")
        old = TableRef(name="empty_t2", key_cols=("id",))
        new = TableRef(name="old_t", key_cols=("id",))
        result = execute_diff(con, old, new, "_zset_all_ins")
        zr = result.unwrap()
        assert zr.stats.insertions == 3
        assert zr.stats.deletions == 0

    def test_stats_sum_to_total(self, con, old_ref, new_ref):
        """insertions + deletions + unchanged == total."""
        result = execute_diff(con, old_ref, new_ref, "_zset_sum")
        s = result.unwrap().stats
        assert s.insertions + s.deletions + s.unchanged == s.total_rows

    def test_net_change_is_insertions_minus_deletions(self, con, old_ref, new_ref):
        """net_change == insertions - deletions."""
        result = execute_diff(con, old_ref, new_ref, "_zset_net")
        s = result.unwrap().stats
        assert s.net_change == s.insertions - s.deletions


# ---------------------------------------------------------------------------
# ZSetStats properties
# ---------------------------------------------------------------------------

class TestZSetStats:
    def test_change_rate_pct(self):
        s = ZSetStats(total_rows=100, insertions=5, deletions=3, unchanged=92, net_change=2)
        assert s.change_rate_pct == 8.0

    def test_change_rate_pct_zero_total(self):
        s = ZSetStats(total_rows=0, insertions=0, deletions=0, unchanged=0, net_change=0)
        assert s.change_rate_pct == 0.0


# ---------------------------------------------------------------------------
# Query algebra immutability tests
# ---------------------------------------------------------------------------

class TestQueryAlgebraImmutability:
    def test_ingest_op_frozen(self):
        from pathlib import Path
        op = IngestOp(source_path=Path("/data.csv"), target_table="t")
        with pytest.raises(AttributeError):
            op.target_table = "changed"

    def test_ingest_plan_table_names(self):
        from pathlib import Path
        plan = IngestPlan(operations=(
            IngestOp(source_path=Path("/a.csv"), target_table="t1"),
            IngestOp(source_path=Path("/b.csv"), target_table="t2"),
            IngestOp(source_path=Path("/c.csv"), target_table="t1"),
        ))
        assert plan.table_names == ("t1", "t2")

    def test_anomaly_check_frozen(self):
        ac = AnomalyCheck(name="test", table="t", query="SELECT 1", severity="low")
        with pytest.raises(AttributeError):
            ac.name = "changed"

    def test_anomaly_result_is_anomalous(self):
        ac = AnomalyCheck(name="test", table="t", query="SELECT 1", severity="low")
        assert AnomalyResult(check=ac, count=5).is_anomalous
        assert not AnomalyResult(check=ac, count=0).is_anomalous

    def test_validation_outcome_passed(self):
        rule = ValidationRule(
            name="test", category="identity",
            description="desc", count_query="SELECT 1",
        )
        assert ValidationOutcome(rule=rule, total_checked=10, issues_found=0).passed
        assert not ValidationOutcome(rule=rule, total_checked=10, issues_found=3).passed

    def test_match_config_with_zset_table(self):
        cfg = MatchConfig(
            old_table="old", new_table="new",
            key_cols=("id",), zset_table="",
        )
        cfg2 = cfg.with_zset_table("_zset_test")
        assert cfg2.zset_table == "_zset_test"
        assert cfg.zset_table == ""  # original unchanged

    def test_predefined_anomaly_checks_exist(self):
        assert len(ANOMALY_CHECKS) >= 10
        for ac in ANOMALY_CHECKS:
            assert ac.severity in ("high", "medium", "low")

    def test_predefined_match_configs_exist(self):
        assert len(MATCH_CONFIGS) == 2
        assert MATCH_CONFIGS[0].old_table == "beneficiary_summary"
        assert MATCH_CONFIGS[1].old_table == "carrier_claims"


# ---------------------------------------------------------------------------
# FieldDelta tests
# ---------------------------------------------------------------------------

class TestFieldDelta:
    def test_frozen(self):
        fd = FieldDelta(column="X", mismatches=5, total_matched=100, mismatch_pct=5.0)
        with pytest.raises(AttributeError):
            fd.column = "Y"

    def test_numeric_fields(self):
        fd = FieldDelta(
            column="AMT", mismatches=2, total_matched=10, mismatch_pct=20.0,
            sum_abs_delta=150.5, avg_abs_delta=75.25, max_abs_delta=100.0,
        )
        assert fd.sum_abs_delta == 150.5
        assert fd.avg_abs_delta == 75.25
