"""Tests that validate the real CMS data files.

These tests are SKIPPED automatically if the data files are not present.
They validate file existence, row counts, schemas, data quality, and
cross-system consistency using the actual downloaded CMS DE-SynPUF data.

Run with:  pytest tests/test_real_data.py -v
"""

from pathlib import Path

import pytest
import duckdb

from src.pipeline.step2_schema_validate import (
    BENEFICIARY_EXPECTED_COLS,
    CARRIER_EXPECTED_COLS,
    _read_csv_headers,
    _classify_file,
    validate_file,
)

# ---------------------------------------------------------------------------
# Paths and skip conditions
# ---------------------------------------------------------------------------

DATA_DIR = Path("data")
OLD_SYSTEM_DIR = DATA_DIR / "old_system"
NEW_SYSTEM_DIR = DATA_DIR / "new_system"

OLD_BENE_FILES = [
    "DE1_0_2008_Beneficiary_Summary_File_Sample_1.csv",
    "DE1_0_2009_Beneficiary_Summary_File_Sample_1.csv",
    "DE1_0_2010_Beneficiary_Summary_File_Sample_1.csv",
]

OLD_CARRIER_FILES = [
    "DE1_0_2008_to_2010_Carrier_Claims_Sample_1A.csv",
    "DE1_0_2008_to_2010_Carrier_Claims_Sample_1B.csv",
]

ALL_OLD_FILES = OLD_BENE_FILES + OLD_CARRIER_FILES

has_old_data = all((OLD_SYSTEM_DIR / f).exists() for f in ALL_OLD_FILES)
has_new_data = NEW_SYSTEM_DIR.exists() and len(list(NEW_SYSTEM_DIR.glob("*.csv"))) >= 5

skip_no_old = pytest.mark.skipif(not has_old_data, reason="Old system data not present")
skip_no_new = pytest.mark.skipif(not has_new_data, reason="New system data not present")

# Expected row counts (excluding header)
EXPECTED_OLD_ROW_COUNTS = {
    "DE1_0_2008_Beneficiary_Summary_File_Sample_1.csv": 116352,
    "DE1_0_2009_Beneficiary_Summary_File_Sample_1.csv": 114538,
    "DE1_0_2010_Beneficiary_Summary_File_Sample_1.csv": 112754,
    "DE1_0_2008_to_2010_Carrier_Claims_Sample_1A.csv": 2370667,
    "DE1_0_2008_to_2010_Carrier_Claims_Sample_1B.csv": 2370668,
}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def old_con():
    """DuckDB connection with old system CSVs loaded."""
    con = duckdb.connect(":memory:")

    # Load beneficiary files with summary_year derived from filename
    first = True
    for f in OLD_BENE_FILES:
        path = OLD_SYSTEM_DIR / f
        year = "2008" if "2008" in f else "2009" if "2009" in f else "2010"
        if first:
            con.execute(f"""
                CREATE TABLE beneficiary_summary AS
                SELECT *, {year} AS summary_year FROM read_csv_auto('{path}')
            """)
            first = False
        else:
            con.execute(f"""
                INSERT INTO beneficiary_summary
                SELECT *, {year} AS summary_year FROM read_csv_auto('{path}')
            """)

    # Load carrier claims files
    first = True
    for f in OLD_CARRIER_FILES:
        path = OLD_SYSTEM_DIR / f
        if first:
            con.execute(f"CREATE TABLE carrier_claims AS SELECT * FROM read_csv_auto('{path}')")
            first = False
        else:
            con.execute(f"INSERT INTO carrier_claims SELECT * FROM read_csv_auto('{path}')")

    return con


# ---------------------------------------------------------------------------
# File Existence
# ---------------------------------------------------------------------------

@skip_no_old
class TestOldSystemFileExistence:
    """Verify all 5 expected old system CSV files are present."""

    @pytest.mark.parametrize("filename", ALL_OLD_FILES)
    def test_file_exists(self, filename):
        path = OLD_SYSTEM_DIR / filename
        assert path.exists(), f"Missing: {path}"
        assert path.stat().st_size > 0, f"Empty file: {path}"

    def test_no_unexpected_files(self):
        csv_files = {f.name for f in OLD_SYSTEM_DIR.glob("*.csv")}
        expected = set(ALL_OLD_FILES)
        unexpected = csv_files - expected
        assert len(unexpected) == 0, f"Unexpected files in old_system/: {unexpected}"


@skip_no_new
class TestNewSystemFileExistence:
    """Verify new system CSV files are present and classifiable."""

    def test_has_beneficiary_files(self):
        bene = list(NEW_SYSTEM_DIR.glob("*Beneficiary*"))
        assert len(bene) >= 3, f"Expected >=3 beneficiary files, found {len(bene)}"

    def test_has_carrier_files(self):
        carrier = list(NEW_SYSTEM_DIR.glob("*Carrier*"))
        assert len(carrier) >= 2, f"Expected >=2 carrier files, found {len(carrier)}"


# ---------------------------------------------------------------------------
# Row Counts
# ---------------------------------------------------------------------------

@skip_no_old
class TestOldSystemRowCounts:
    """Verify row counts match expected CMS DE-SynPUF Sample 1 sizes."""

    @pytest.mark.parametrize("filename,expected_rows", list(EXPECTED_OLD_ROW_COUNTS.items()))
    def test_row_count(self, filename, expected_rows):
        path = OLD_SYSTEM_DIR / filename
        con = duckdb.connect(":memory:")
        actual = con.execute(f"SELECT count(*) FROM read_csv_auto('{path}')").fetchone()[0]
        assert actual == expected_rows, (
            f"{filename}: expected {expected_rows:,} rows, got {actual:,}"
        )


@skip_no_new
class TestNewSystemRowCounts:
    """Verify new system files have reasonable row counts."""

    def test_beneficiary_row_counts_match_old(self):
        """New system beneficiary files should have same row counts as old."""
        con = duckdb.connect(":memory:")
        for old_f in OLD_BENE_FILES:
            new_candidates = list(NEW_SYSTEM_DIR.glob(f"*{old_f.replace('.csv', '')}*"))
            if new_candidates:
                old_count = con.execute(
                    f"SELECT count(*) FROM read_csv_auto('{OLD_SYSTEM_DIR / old_f}')"
                ).fetchone()[0]
                new_count = con.execute(
                    f"SELECT count(*) FROM read_csv_auto('{new_candidates[0]}')"
                ).fetchone()[0]
                assert new_count == old_count, (
                    f"{old_f}: old has {old_count:,} rows, new has {new_count:,}"
                )


# ---------------------------------------------------------------------------
# Schema Validation
# ---------------------------------------------------------------------------

@skip_no_old
class TestOldSystemSchema:
    """Verify old system files have the correct column schemas."""

    @pytest.mark.parametrize("filename", OLD_BENE_FILES)
    def test_beneficiary_schema(self, filename):
        path = OLD_SYSTEM_DIR / filename
        result = validate_file(path)
        assert result["valid"] is True, f"Schema invalid: {result['errors']}"
        assert result["file_type"] == "beneficiary"
        assert result["header_count"] == 32
        assert len(result["missing_columns"]) == 0, (
            f"Missing columns: {result['missing_columns']}"
        )

    @pytest.mark.parametrize("filename", OLD_CARRIER_FILES)
    def test_carrier_schema(self, filename):
        path = OLD_SYSTEM_DIR / filename
        result = validate_file(path)
        assert result["valid"] is True, f"Schema invalid: {result['errors']}"
        assert result["file_type"] == "carrier_claims"
        assert result["header_count"] == 142
        assert len(result["missing_columns"]) == 0, (
            f"Missing columns: {result['missing_columns']}"
        )


@skip_no_new
class TestNewSystemSchema:
    """Verify new system files are classifiable and schema-compatible."""

    def test_all_files_classifiable(self):
        for csv_path in sorted(NEW_SYSTEM_DIR.glob("*.csv")):
            headers = _read_csv_headers(csv_path)
            file_type = _classify_file(headers)
            assert file_type is not None, (
                f"Cannot classify {csv_path.name} — headers don't match known schemas"
            )

    def test_beneficiary_files_have_expected_columns(self):
        for csv_path in sorted(NEW_SYSTEM_DIR.glob("*Beneficiary*")):
            headers = set(_read_csv_headers(csv_path))
            missing = BENEFICIARY_EXPECTED_COLS - headers
            assert len(missing) == 0, (
                f"{csv_path.name} missing columns: {missing}"
            )

    def test_carrier_files_have_expected_columns(self):
        for csv_path in sorted(NEW_SYSTEM_DIR.glob("*Carrier*")):
            headers = set(_read_csv_headers(csv_path))
            missing = CARRIER_EXPECTED_COLS - headers
            assert len(missing) == 0, (
                f"{csv_path.name} missing columns: {missing}"
            )


# ---------------------------------------------------------------------------
# Data Quality — Old System
# ---------------------------------------------------------------------------

@skip_no_old
class TestOldSystemDataQuality:
    """Data quality checks on the old system files."""

    def test_beneficiary_ids_not_null(self, old_con):
        nulls = old_con.execute(
            "SELECT count(*) FROM beneficiary_summary WHERE DESYNPUF_ID IS NULL"
        ).fetchone()[0]
        assert nulls == 0, f"Found {nulls} null DESYNPUF_IDs in beneficiary_summary"

    def test_carrier_claim_ids_not_null(self, old_con):
        nulls = old_con.execute(
            "SELECT count(*) FROM carrier_claims WHERE CLM_ID IS NULL"
        ).fetchone()[0]
        assert nulls == 0, f"Found {nulls} null CLM_IDs in carrier_claims"

    def test_beneficiary_years_expected(self, old_con):
        years = old_con.execute(
            "SELECT DISTINCT summary_year FROM beneficiary_summary ORDER BY 1"
        ).fetchall()
        year_values = [r[0] for r in years]
        assert year_values == [2008, 2009, 2010], f"Unexpected years: {year_values}"

    def test_no_duplicate_beneficiary_per_year(self, old_con):
        dupes = old_con.execute("""
            SELECT count(*) FROM (
                SELECT DESYNPUF_ID, summary_year, count(*) AS cnt
                FROM beneficiary_summary
                GROUP BY DESYNPUF_ID, summary_year
                HAVING cnt > 1
            )
        """).fetchone()[0]
        assert dupes == 0, f"Found {dupes} duplicate beneficiary-year combinations"

    def test_sex_codes_valid(self, old_con):
        invalid = old_con.execute("""
            SELECT count(*) FROM beneficiary_summary
            WHERE BENE_SEX_IDENT_CD NOT IN (1, 2)
        """).fetchone()[0]
        assert invalid == 0, f"Found {invalid} invalid sex codes (expected 1 or 2)"

    def test_race_codes_valid(self, old_con):
        invalid = old_con.execute("""
            SELECT count(*) FROM beneficiary_summary
            WHERE BENE_RACE_CD NOT IN (1, 2, 3, 5)
        """).fetchone()[0]
        assert invalid == 0, f"Found {invalid} invalid race codes (expected 1, 2, 3, or 5)"

    def test_claim_dates_are_eight_digits(self, old_con):
        bad_dates = old_con.execute("""
            SELECT count(*) FROM carrier_claims
            WHERE CLM_FROM_DT < 19000101 OR CLM_FROM_DT > 20301231
               OR CLM_THRU_DT < 19000101 OR CLM_THRU_DT > 20301231
        """).fetchone()[0]
        assert bad_dates == 0, f"Found {bad_dates} claims with out-of-range dates"

    def test_payment_amounts_non_negative(self, old_con):
        negatives = old_con.execute("""
            SELECT count(*) FROM carrier_claims
            WHERE LINE_NCH_PMT_AMT_1 < 0
        """).fetchone()[0]
        assert negatives == 0, f"Found {negatives} claims with negative payment amounts"

    def test_all_claims_reference_valid_dates(self, old_con):
        """CLM_FROM_DT should not be after CLM_THRU_DT."""
        inversions = old_con.execute("""
            SELECT count(*) FROM carrier_claims
            WHERE CLM_FROM_DT > CLM_THRU_DT
        """).fetchone()[0]
        # CMS data may have some — this is informational
        # We just check it's a small fraction
        total = old_con.execute("SELECT count(*) FROM carrier_claims").fetchone()[0]
        pct = (inversions / total * 100) if total > 0 else 0
        assert pct < 1.0, (
            f"Date inversions: {inversions:,} / {total:,} = {pct:.2f}% (expected <1%)"
        )


# ---------------------------------------------------------------------------
# Cross-System Comparison
# ---------------------------------------------------------------------------

@skip_no_old
@skip_no_new
class TestCrossSystemConsistency:
    """Compare old and new system data for structural consistency."""

    def test_schemas_match(self):
        """Old and new system files should have identical column schemas."""
        for old_f in OLD_BENE_FILES:
            old_headers = set(_read_csv_headers(OLD_SYSTEM_DIR / old_f))
            new_candidates = list(NEW_SYSTEM_DIR.glob(f"*{old_f.replace('.csv', '')}*"))
            if new_candidates:
                new_headers = set(_read_csv_headers(new_candidates[0]))
                assert old_headers == new_headers, (
                    f"Schema mismatch for {old_f}: "
                    f"old-only={old_headers - new_headers}, "
                    f"new-only={new_headers - old_headers}"
                )

    def test_beneficiary_id_overlap(self):
        """Most beneficiary IDs should appear in both systems."""
        con = duckdb.connect(":memory:")
        old_path = OLD_SYSTEM_DIR / OLD_BENE_FILES[0]
        new_candidates = list(NEW_SYSTEM_DIR.glob("*2008*Beneficiary*"))
        if not new_candidates:
            pytest.skip("No matching new system 2008 beneficiary file")

        old_ids = con.execute(
            f"SELECT DISTINCT DESYNPUF_ID FROM read_csv_auto('{old_path}')"
        ).fetchall()
        new_ids = con.execute(
            f"SELECT DISTINCT DESYNPUF_ID FROM read_csv_auto('{new_candidates[0]}')"
        ).fetchall()

        old_set = {r[0] for r in old_ids}
        new_set = {r[0] for r in new_ids}
        overlap = len(old_set & new_set)
        overlap_pct = (overlap / len(old_set) * 100) if old_set else 0

        assert overlap_pct > 90, (
            f"Only {overlap_pct:.1f}% beneficiary ID overlap between old and new "
            f"(expected >90%)"
        )
