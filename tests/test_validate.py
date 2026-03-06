"""Tests for the VALIDATE stage."""

from src.validate import (
    check_key_integrity,
    check_temporal_consistency,
    check_demographic_consistency,
    check_financial_reconciliation,
    check_coverage_period,
    check_esrd_consistency,
    check_state_codes,
    check_diagnosis_codes,
    check_npi_format,
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

    def test_financial_recon_has_distribution(self, con):
        results = check_financial_reconciliation(con)
        medreimb = next(r for r in results if r.check_name == "financial_recon_medreimb_car")
        assert len(medreimb.details) == 1
        assert "distribution" in medreimb.details[0]
        dist = medreimb.details[0]["distribution"]
        assert "exact_match_lte_0.01" in dist
        assert "diff_over_100.00" in dist


class TestCoveragePeriod:
    def test_coverage_months_in_range(self, con):
        results = check_coverage_period(con)
        # Test data has all coverage values within 0-12
        for r in results:
            assert r.category == "coverage"
            assert r.issues_found == 0

    def test_all_four_columns_checked(self, con):
        results = check_coverage_period(con)
        assert len(results) == 4
        names = {r.check_name for r in results}
        assert "coverage_range_bene_hi_cvrage_tot_mons" in names
        assert "coverage_range_bene_smi_cvrage_tot_mons" in names
        assert "coverage_range_bene_hmo_cvrage_tot_mons" in names
        assert "coverage_range_plan_cvrg_mos_num" in names


class TestEsrdConsistency:
    def test_no_esrd_regression(self, con):
        results = check_esrd_consistency(con)
        esrd = results[0]
        # Test data has no ESRD regressions (all BENE_ESRD_IND = 0)
        assert esrd.check_name == "esrd_regression"
        assert esrd.issues_found == 0


class TestStateCodes:
    def test_valid_state_codes(self, con):
        results = check_state_codes(con)
        invalid = next(r for r in results if r.check_name == "invalid_state_code")
        # All test state codes (26, 10, 05, 36) are in 1-56 range
        assert invalid.issues_found == 0

    def test_state_changes_detected(self, con):
        results = check_state_codes(con)
        changes = next(r for r in results if r.check_name == "state_change_across_years")
        # Only BENE_A has 2 years, same state code 26 both years
        assert changes.issues_found == 0


class TestDiagnosisCodes:
    def test_icd9_format_check_runs(self, con):
        results = check_diagnosis_codes(con)
        # Test data has NULL diagnosis codes, so no values to check
        # The function should return empty or a result with 0 total
        assert isinstance(results, list)


class TestNpiFormat:
    def test_npi_format_check_runs(self, con):
        results = check_npi_format(con)
        # Test data has NULL NPIs, so no values to check
        assert isinstance(results, list)


class TestFullValidation:
    def test_run_returns_all_checks(self, con):
        results = validate_run(con)
        categories = {r.category for r in results}
        assert "identity" in categories
        assert "temporal" in categories
        assert "demographic" in categories
        assert "financial" in categories
        assert "coverage" in categories
        assert "clinical" in categories

    def test_run_returns_expected_count(self, con):
        results = validate_run(con)
        # 3 identity + 3 temporal + 3 demographic + 4 coverage + 1 ESRD
        # + 2 state + 3 financial = 19 (ICD-9 and NPI may be 0 if no data)
        assert len(results) >= 19

    def test_validation_result_properties(self, con):
        results = validate_run(con)
        for r in results:
            assert r.check_name
            assert r.category
            assert r.total_checked >= 0
            assert r.issues_found >= 0
            assert isinstance(r.passed, bool)
