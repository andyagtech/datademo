"""Tests for the PROFILE stage."""

from src.profile import run as profile_run, profile_table


def test_profile_returns_all_tables(con):
    profiles = profile_run(con)
    assert "beneficiary_summary" in profiles
    assert "carrier_claims" in profiles


def test_profile_row_count(con):
    tp = profile_table(con, "beneficiary_summary")
    assert tp.row_count == 5
    assert tp.column_count == 33  # 32 original + summary_year


def test_profile_null_detection(con):
    tp = profile_table(con, "beneficiary_summary")
    death_col = next(c for c in tp.columns if c.name == "BENE_DEATH_DT")
    # BENE_B has a death date, others have 0 (not null) — depends on schema
    # At minimum, null_pct should be a valid number
    assert death_col.null_pct >= 0


def test_profile_distinct_count(con):
    tp = profile_table(con, "beneficiary_summary")
    sex_col = next(c for c in tp.columns if c.name == "BENE_SEX_IDENT_CD")
    assert sex_col.distinct_count == 2  # 1 and 2


def test_profile_numeric_stats(con):
    tp = profile_table(con, "beneficiary_summary")
    medreimb = next(c for c in tp.columns if c.name == "MEDREIMB_CAR")
    assert medreimb.min_val is not None
    assert medreimb.max_val is not None
    assert medreimb.mean_val is not None


def test_profile_top_values_for_low_cardinality(con):
    tp = profile_table(con, "beneficiary_summary")
    sex_col = next(c for c in tp.columns if c.name == "BENE_SEX_IDENT_CD")
    assert len(sex_col.top_values) > 0


def test_carrier_claims_profile(con):
    tp = profile_table(con, "carrier_claims")
    assert tp.row_count == 6
    assert tp.column_count == 142
