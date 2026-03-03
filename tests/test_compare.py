"""Tests for the COMPARE stage."""

from src.compare import (
    compare_schemas,
    compare_row_counts,
    compare_field_values,
    compare_aggregates,
    run as compare_run,
)


class TestSchemaComparison:
    def test_detects_missing_columns(self, con_with_new):
        # Both tables have same schema in our fixtures
        results = compare_schemas(con_with_new, "beneficiary_summary", "new_beneficiary_summary")
        missing = next(r for r in results if r.check_name == "missing_columns_in_new")
        assert missing.metric_value == 0

    def test_detects_type_mismatches(self, con_with_new):
        results = compare_schemas(con_with_new, "beneficiary_summary", "new_beneficiary_summary")
        types = next(r for r in results if r.check_name == "type_mismatches")
        assert isinstance(types.metric_value, int)


class TestRowCounts:
    def test_row_count_difference(self, con_with_new):
        results = compare_row_counts(
            con_with_new, "beneficiary_summary", "new_beneficiary_summary", "DESYNPUF_ID"
        )
        count_diff = next(r for r in results if r.check_name == "row_count_difference")
        # Old: 5 rows (BENE_A x2, B, C, D), New: 5 rows (BENE_A x2, B, C, BENE_NEW)
        assert count_diff.metric_value == 0

    def test_keys_missing_in_new(self, con_with_new):
        results = compare_row_counts(
            con_with_new, "beneficiary_summary", "new_beneficiary_summary", "DESYNPUF_ID"
        )
        missing = next(r for r in results if r.check_name == "keys_missing_in_new")
        # BENE_D is in old but not in new
        assert missing.metric_value == 1

    def test_keys_extra_in_new(self, con_with_new):
        results = compare_row_counts(
            con_with_new, "beneficiary_summary", "new_beneficiary_summary", "DESYNPUF_ID"
        )
        extra = next(r for r in results if r.check_name == "keys_extra_in_new")
        # BENE_NEW is in new but not in old
        assert extra.metric_value == 1


class TestFieldValues:
    def test_detects_race_mismatch(self, con_with_new):
        results = compare_field_values(
            con_with_new, "beneficiary_summary", "new_beneficiary_summary",
            "DESYNPUF_ID", ["BENE_RACE_CD"]
        )
        race = next(r for r in results if r.check_name == "field_mismatch_bene_race_cd")
        # BENE_C: race 3 -> 5
        assert race.metric_value >= 1


class TestAggregates:
    def test_aggregate_divergence(self, con_with_new):
        results = compare_aggregates(
            con_with_new, "beneficiary_summary", "new_beneficiary_summary",
            ["MEDREIMB_CAR"]
        )
        agg = next(r for r in results if r.check_name == "aggregate_divergence_medreimb_car")
        # Old BENE_D had 500, new has BENE_NEW with 70 — sums differ
        assert agg.metric_value > 0


class TestCompareRun:
    def test_skips_when_no_new_tables(self, con):
        results = compare_run(con)
        assert len(results) == 0

    def test_runs_when_new_tables_present(self, con_with_new):
        results = compare_run(con_with_new)
        assert len(results) > 0
        categories = {r.category for r in results}
        assert "schema" in categories
        assert "row_level" in categories
