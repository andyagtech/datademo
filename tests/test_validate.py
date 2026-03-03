"""Tests for the VALIDATE stage."""

from src.validate import (
    check_key_integrity,
    check_temporal_consistency,
    check_demographic_consistency,
    check_financial_reconciliation,
    run as validate_run,
)


class TestKeyIntegrity:
    def test_orphan_claims_detected(self, con):
        results = check_key_integrity(con)
        orphan = next(r for r in results if r.check_name == "orphan_claims_beneficiaries")
        # ORPHAN_X is in claims but not in beneficiary_summary
        assert orphan.issues_found == 1

    def test_beneficiaries_without_claims(self, con):
        results = check_key_integrity(con)
        no_claims = next(r for r in results if r.check_name == "beneficiaries_without_claims")
        # BENE_C has no claims
        assert no_claims.issues_found == 1

    def test_duplicate_claim_ids(self, con):
        results = check_key_integrity(con)
        dups = next(r for r in results if r.check_name == "duplicate_claim_ids")
        # All claim IDs are unique in test data
        assert dups.issues_found == 0


class TestTemporalConsistency:
    def test_claims_after_death(self, con):
        results = check_temporal_consistency(con)
        post_death = next(r for r in results if r.check_name == "claims_after_death")
        # BENE_B died 20080615, has claim on 20080901
        assert post_death.issues_found >= 1

    def test_date_inversion(self, con):
        results = check_temporal_consistency(con)
        inversion = next(r for r in results if r.check_name == "claim_date_inversion")
        # BENE_D has CLM_FROM_DT=20080815 > CLM_THRU_DT=20080801
        assert inversion.issues_found == 1


class TestDemographicConsistency:
    def test_no_sex_changes(self, con):
        results = check_demographic_consistency(con)
        sex = next(r for r in results if r.check_name == "sex_change_across_years")
        # BENE_A appears in 2008 and 2009 with same sex=1
        assert sex.issues_found == 0

    def test_no_race_changes(self, con):
        results = check_demographic_consistency(con)
        race = next(r for r in results if r.check_name == "race_change_across_years")
        assert race.issues_found == 0

    def test_no_dob_changes(self, con):
        results = check_demographic_consistency(con)
        dob = next(r for r in results if r.check_name == "dob_change_across_years")
        assert dob.issues_found == 0


class TestFinancialReconciliation:
    def test_medreimb_car_reconciliation(self, con):
        results = check_financial_reconciliation(con)
        medreimb = next(r for r in results if r.check_name == "financial_recon_medreimb_car")
        # BENE_A 2008: 2 claims with pmt1=150 each = 300, summary says 300 -> match
        # BENE_A 2009: 1 claim with pmt1=310, summary says 310 -> match
        assert medreimb.total_checked > 0

    def test_financial_recon_creates_table(self, con):
        check_financial_reconciliation(con)
        tables = [r[0] for r in con.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_name = '_financial_recon'"
        ).fetchall()]
        assert "_financial_recon" in tables


class TestFullValidation:
    def test_run_returns_all_checks(self, con):
        results = validate_run(con)
        categories = {r.category for r in results}
        assert "identity" in categories
        assert "temporal" in categories
        assert "demographic" in categories
        assert "financial" in categories

    def test_run_returns_expected_count(self, con):
        results = validate_run(con)
        # 3 identity + 2 temporal + 3 demographic + 3 financial = 11
        assert len(results) == 11

    def test_validation_result_properties(self, con):
        results = validate_run(con)
        for r in results:
            assert r.check_name
            assert r.category
            assert r.total_checked >= 0
            assert r.issues_found >= 0
            assert isinstance(r.passed, bool)
