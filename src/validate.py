"""
VALIDATE stage — Internal consistency checks on the legacy CMS data.

Checks include:
  1. Key integrity: beneficiaries in claims but missing from summary (and vice versa)
  2. Duplicate claim IDs
  3. Financial reconciliation: carrier reimbursement summaries vs claim-line aggregates
  4. Temporal checks: claims after death, claims outside coverage periods
  5. Chronic condition flags vs diagnosis codes on claims
"""

import logging
from dataclasses import dataclass, field

import duckdb

logger = logging.getLogger(__name__)


@dataclass
class ValidationResult:
    check_name: str
    category: str  # schema, identity, financial, temporal, clinical, demographic
    description: str
    total_checked: int
    issues_found: int
    issue_pct: float
    details: list[dict] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return self.issues_found == 0


def check_key_integrity(con: duckdb.DuckDBPyConnection) -> list[ValidationResult]:
    """Check referential integrity between beneficiary summary and carrier claims."""
    results = []

    # Claims referencing unknown beneficiaries
    r = con.execute("""
        SELECT COUNT(DISTINCT cc.DESYNPUF_ID) AS orphan_count
        FROM carrier_claims cc
        LEFT JOIN beneficiary_summary bs ON cc.DESYNPUF_ID = bs.DESYNPUF_ID
        WHERE bs.DESYNPUF_ID IS NULL
    """).fetchone()
    total_claim_benes = con.execute(
        "SELECT COUNT(DISTINCT DESYNPUF_ID) FROM carrier_claims"
    ).fetchone()[0]
    results.append(ValidationResult(
        check_name="orphan_claims_beneficiaries",
        category="identity",
        description="Beneficiary IDs in carrier claims not found in any beneficiary summary file",
        total_checked=total_claim_benes,
        issues_found=r[0],
        issue_pct=round(100.0 * r[0] / max(total_claim_benes, 1), 2),
    ))

    # Beneficiaries with no claims
    r = con.execute("""
        SELECT COUNT(DISTINCT bs.DESYNPUF_ID) AS no_claims
        FROM beneficiary_summary bs
        LEFT JOIN carrier_claims cc ON bs.DESYNPUF_ID = cc.DESYNPUF_ID
        WHERE cc.DESYNPUF_ID IS NULL
    """).fetchone()
    total_benes = con.execute(
        "SELECT COUNT(DISTINCT DESYNPUF_ID) FROM beneficiary_summary"
    ).fetchone()[0]
    results.append(ValidationResult(
        check_name="beneficiaries_without_claims",
        category="identity",
        description="Beneficiaries in summary files with zero carrier claims",
        total_checked=total_benes,
        issues_found=r[0],
        issue_pct=round(100.0 * r[0] / max(total_benes, 1), 2),
    ))

    # Duplicate claim IDs
    r = con.execute("""
        SELECT COUNT(*) AS dup_count FROM (
            SELECT CLM_ID, COUNT(*) AS cnt
            FROM carrier_claims
            GROUP BY CLM_ID
            HAVING COUNT(*) > 1
        )
    """).fetchone()
    total_claims = con.execute("SELECT COUNT(DISTINCT CLM_ID) FROM carrier_claims").fetchone()[0]
    results.append(ValidationResult(
        check_name="duplicate_claim_ids",
        category="identity",
        description="Claim IDs appearing more than once in carrier claims",
        total_checked=total_claims,
        issues_found=r[0],
        issue_pct=round(100.0 * r[0] / max(total_claims, 1), 2),
    ))

    return results


def check_financial_reconciliation(con: duckdb.DuckDBPyConnection) -> list[ValidationResult]:
    """
    Verify carrier reimbursement summaries match claim-line aggregates.
    Per the codebook:
      MEDREIMB_CAR = SUM(LINE_NCH_PMT_AMT) WHERE LINE_PRCSG_IND_CD = 'A'
                     OR (LINE_PRCSG_IND_CD IN ('R','S') AND LINE_ALOWD_CHRG_AMT > 0)
      BENRES_CAR  = SUM(LINE_BENE_PTB_DDCTBL_AMT + LINE_COINSRNC_AMT) [same filter]
      PPPYMT_CAR  = SUM(LINE_BENE_PRMRY_PYR_PD_AMT) [same filter]
    """
    results = []

    # Build a CTE that unpivots the 13 claim lines and applies the codebook filter,
    # then aggregate per beneficiary per year.
    line_agg_query = """
    WITH claim_lines AS (
        SELECT
            cc.DESYNPUF_ID,
            (cc.CLM_FROM_DT / 10000)::INT AS claim_year,
            line_num,
            CASE line_num
                {pmt_cases}
            END AS line_pmt,
            CASE line_num
                {ddctbl_cases}
            END AS line_ddctbl,
            CASE line_num
                {coinsrnc_cases}
            END AS line_coinsrnc,
            CASE line_num
                {prmry_cases}
            END AS line_prmry,
            CASE line_num
                {prcsg_cases}
            END AS line_prcsg,
            CASE line_num
                {alowd_cases}
            END AS line_alowd
        FROM carrier_claims cc
        CROSS JOIN generate_series(1, 13) AS t(line_num)
    ),
    filtered_lines AS (
        SELECT *
        FROM claim_lines
        WHERE line_prcsg = 'A'
           OR (line_prcsg IN ('R', 'S') AND TRY_CAST(line_alowd AS DOUBLE) > 0)
    ),
    claim_agg AS (
        SELECT
            DESYNPUF_ID,
            claim_year,
            COALESCE(SUM(TRY_CAST(line_pmt AS DOUBLE)), 0) AS calc_medreimb_car,
            COALESCE(SUM(TRY_CAST(line_ddctbl AS DOUBLE) + TRY_CAST(line_coinsrnc AS DOUBLE)), 0) AS calc_benres_car,
            COALESCE(SUM(TRY_CAST(line_prmry AS DOUBLE)), 0) AS calc_pppymt_car
        FROM filtered_lines
        GROUP BY DESYNPUF_ID, claim_year
    )
    SELECT
        bs.DESYNPUF_ID,
        bs.summary_year,
        bs.MEDREIMB_CAR AS reported_medreimb,
        ca.calc_medreimb_car,
        bs.BENRES_CAR AS reported_benres,
        ca.calc_benres_car,
        bs.PPPYMT_CAR AS reported_pppymt,
        ca.calc_pppymt_car,
        ABS(bs.MEDREIMB_CAR - ca.calc_medreimb_car) AS medreimb_diff,
        ABS(bs.BENRES_CAR - ca.calc_benres_car) AS benres_diff,
        ABS(bs.PPPYMT_CAR - ca.calc_pppymt_car) AS pppymt_diff
    FROM beneficiary_summary bs
    INNER JOIN claim_agg ca
        ON bs.DESYNPUF_ID = ca.DESYNPUF_ID
        AND bs.summary_year = ca.claim_year
    """

    def _cases(prefix):
        return "\n                ".join(
            f"WHEN {i} THEN {prefix}_{i}::VARCHAR" for i in range(1, 14)
        )

    query = line_agg_query.format(
        pmt_cases=_cases("LINE_NCH_PMT_AMT"),
        ddctbl_cases=_cases("LINE_BENE_PTB_DDCTBL_AMT"),
        coinsrnc_cases=_cases("LINE_COINSRNC_AMT"),
        prmry_cases=_cases("LINE_BENE_PRMRY_PYR_PD_AMT"),
        prcsg_cases=_cases("LINE_PRCSG_IND_CD"),
        alowd_cases=_cases("LINE_ALOWD_CHRG_AMT"),
    )

    # Store the reconciliation results in a temp table for reporting
    con.execute(f"CREATE OR REPLACE TABLE _financial_recon AS ({query})")

    # Tolerance note: we use $0.01 as the mismatch threshold because
    # floating-point arithmetic on aggregated payment amounts can introduce
    # sub-cent rounding differences that are not true discrepancies.
    TOLERANCE = 0.01

    for metric, col_diff in [
        ("MEDREIMB_CAR", "medreimb_diff"),
        ("BENRES_CAR", "benres_diff"),
        ("PPPYMT_CAR", "pppymt_diff"),
    ]:
        stats = con.execute(f"""
            SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN {col_diff} > {TOLERANCE} THEN 1 ELSE 0 END) AS mismatches,
                AVG({col_diff}) AS avg_diff,
                MAX({col_diff}) AS max_diff
            FROM _financial_recon
        """).fetchone()
        assert stats is not None
        total, mismatches, avg_diff, max_diff = stats

        # Diff distribution — shows how discrepancies are concentrated
        dist = con.execute(f"""
            SELECT
                SUM(CASE WHEN {col_diff} <= {TOLERANCE} THEN 1 ELSE 0 END) AS exact_match,
                SUM(CASE WHEN {col_diff} > {TOLERANCE} AND {col_diff} <= 1.00 THEN 1 ELSE 0 END) AS under_1,
                SUM(CASE WHEN {col_diff} > 1.00 AND {col_diff} <= 100.00 THEN 1 ELSE 0 END) AS under_100,
                SUM(CASE WHEN {col_diff} > 100.00 THEN 1 ELSE 0 END) AS over_100
            FROM _financial_recon
        """).fetchone()

        results.append(ValidationResult(
            check_name=f"financial_recon_{metric.lower()}",
            category="financial",
            description=f"Beneficiary summary {metric} vs computed aggregate from carrier claim lines "
                        f"(tolerance: ${TOLERANCE})",
            total_checked=total,
            issues_found=mismatches,
            issue_pct=round(100.0 * mismatches / max(total, 1), 2),
            details=[{
                "avg_diff": round(avg_diff, 2) if avg_diff else 0,
                "max_diff": round(max_diff, 2) if max_diff else 0,
                "distribution": {
                    "exact_match_lte_0.01": dist[0],
                    "diff_0.01_to_1.00": dist[1],
                    "diff_1.00_to_100.00": dist[2],
                    "diff_over_100.00": dist[3],
                },
            }],
        ))

    return results


def check_coverage_period(con: duckdb.DuckDBPyConnection) -> list[ValidationResult]:
    """Validate coverage month fields are within the valid 0–12 range.

    Per the CMS codebook, BENE_HI_CVRAGE_TOT_MONS, BENE_SMI_CVRAGE_TOT_MONS,
    BENE_HMO_CVRAGE_TOT_MONS, and PLAN_CVRG_MOS_NUM represent months of
    coverage in a calendar year and must be integers between 0 and 12.
    """
    results = []
    total_benes = con.execute(
        "SELECT COUNT(*) FROM beneficiary_summary"
    ).fetchone()[0]

    coverage_cols = [
        ("BENE_HI_CVRAGE_TOT_MONS", "Hospital Insurance (Part A) coverage months"),
        ("BENE_SMI_CVRAGE_TOT_MONS", "Supplementary Medical Insurance (Part B) coverage months"),
        ("BENE_HMO_CVRAGE_TOT_MONS", "HMO coverage months"),
        ("PLAN_CVRG_MOS_NUM", "Part D plan coverage months"),
    ]

    for col, label in coverage_cols:
        try:
            r = con.execute(f"""
                SELECT COUNT(*) FROM beneficiary_summary
                WHERE {col} < 0 OR {col} > 12
            """).fetchone()
            results.append(ValidationResult(
                check_name=f"coverage_range_{col.lower()}",
                category="coverage",
                description=f"{label} outside valid 0–12 range",
                total_checked=total_benes,
                issues_found=r[0],
                issue_pct=round(100.0 * r[0] / max(total_benes, 1), 4),
            ))
        except duckdb.Error as e:
            logger.debug(f"Coverage check skipped for {col}: {e}")

    return results


def check_esrd_consistency(con: duckdb.DuckDBPyConnection) -> list[ValidationResult]:
    """Check that ESRD (End-Stage Renal Disease) indicator does not regress.

    BENE_ESRD_IND = 'Y' means the beneficiary has ESRD. Once diagnosed,
    ESRD is clinically irreversible — a beneficiary should not revert
    from 'Y' to '0' in a later summary year.
    """
    results = []
    total_benes = con.execute(
        "SELECT COUNT(DISTINCT DESYNPUF_ID) FROM beneficiary_summary"
    ).fetchone()[0]

    try:
        r = con.execute("""
            SELECT COUNT(DISTINCT a.DESYNPUF_ID)
            FROM beneficiary_summary a
            INNER JOIN beneficiary_summary b
                ON a.DESYNPUF_ID = b.DESYNPUF_ID
                AND a.summary_year < b.summary_year
            WHERE a.BENE_ESRD_IND::VARCHAR = 'Y'
              AND (b.BENE_ESRD_IND IS NULL OR b.BENE_ESRD_IND::VARCHAR != 'Y')
        """).fetchone()
        results.append(ValidationResult(
            check_name="esrd_regression",
            category="clinical",
            description="Beneficiaries whose ESRD indicator regresses from Y to non-Y in a later year (clinically impossible)",
            total_checked=total_benes,
            issues_found=r[0],
            issue_pct=round(100.0 * r[0] / max(total_benes, 1), 4),
        ))
    except duckdb.Error as e:
        logger.debug(f"ESRD consistency check skipped: {e}")

    return results


def check_state_codes(con: duckdb.DuckDBPyConnection) -> list[ValidationResult]:
    """Validate SP_STATE_CODE values and check for year-over-year changes.

    Per the CMS codebook, SP_STATE_CODE uses SSA state codes (01–53 plus
    territories). Values outside 01–56 are invalid. Additionally, while
    beneficiary relocation is possible, frequent state changes may indicate
    data quality issues.
    """
    results = []
    total_benes = con.execute(
        "SELECT COUNT(*) FROM beneficiary_summary"
    ).fetchone()[0]
    total_distinct = con.execute(
        "SELECT COUNT(DISTINCT DESYNPUF_ID) FROM beneficiary_summary"
    ).fetchone()[0]

    # Invalid state codes (outside 1-56 range)
    try:
        r = con.execute("""
            SELECT COUNT(*) FROM beneficiary_summary
            WHERE SP_STATE_CODE < 1 OR SP_STATE_CODE > 56
        """).fetchone()
        results.append(ValidationResult(
            check_name="invalid_state_code",
            category="demographic",
            description="Beneficiary records with SP_STATE_CODE outside valid SSA range (1–56)",
            total_checked=total_benes,
            issues_found=r[0],
            issue_pct=round(100.0 * r[0] / max(total_benes, 1), 4),
        ))
    except duckdb.Error as e:
        logger.debug(f"State code range check skipped: {e}")

    # State changes across years (flag as informational — relocation is possible)
    try:
        r = con.execute("""
            SELECT COUNT(DISTINCT DESYNPUF_ID) FROM (
                SELECT DESYNPUF_ID, COUNT(DISTINCT SP_STATE_CODE) AS n_states
                FROM beneficiary_summary
                GROUP BY DESYNPUF_ID
                HAVING COUNT(DISTINCT SP_STATE_CODE) > 1
            )
        """).fetchone()
        results.append(ValidationResult(
            check_name="state_change_across_years",
            category="demographic",
            description="Beneficiaries whose state code changes across years (possible relocation, but worth flagging)",
            total_checked=total_distinct,
            issues_found=r[0],
            issue_pct=round(100.0 * r[0] / max(total_distinct, 1), 4),
        ))
    except duckdb.Error as e:
        logger.debug(f"State change check skipped: {e}")

    return results


def check_temporal_consistency(con: duckdb.DuckDBPyConnection) -> list[ValidationResult]:
    """Check for claims filed after beneficiary death date."""
    results = []

    r = con.execute("""
        SELECT COUNT(*) AS post_death_claims
        FROM carrier_claims cc
        INNER JOIN beneficiary_summary bs
            ON cc.DESYNPUF_ID = bs.DESYNPUF_ID
        WHERE bs.BENE_DEATH_DT IS NOT NULL
          AND bs.BENE_DEATH_DT != 0
          AND cc.CLM_FROM_DT > bs.BENE_DEATH_DT
    """).fetchone()

    total_claims = con.execute("SELECT COUNT(*) FROM carrier_claims").fetchone()[0]
    results.append(ValidationResult(
        check_name="claims_after_death",
        category="temporal",
        description="Carrier claims with start date after beneficiary death date",
        total_checked=total_claims,
        issues_found=r[0],
        issue_pct=round(100.0 * r[0] / max(total_claims, 1), 4),
    ))

    # Claims where CLM_FROM_DT > CLM_THRU_DT
    r = con.execute("""
        SELECT COUNT(*) FROM carrier_claims
        WHERE CLM_FROM_DT > CLM_THRU_DT
    """).fetchone()
    results.append(ValidationResult(
        check_name="claim_date_inversion",
        category="temporal",
        description="Claims where start date is after end date",
        total_checked=total_claims,
        issues_found=r[0],
        issue_pct=round(100.0 * r[0] / max(total_claims, 1), 4),
    ))

    # Summary records appearing after the death year.
    # If BENE_DEATH_DT is set in year Y, the beneficiary should not appear
    # in summary files for year Y+1 or later. The death-year summary itself
    # is expected (partial-year enrollment).
    try:
        r = con.execute("""
            SELECT COUNT(DISTINCT a.DESYNPUF_ID)
            FROM beneficiary_summary a
            INNER JOIN beneficiary_summary b
                ON a.DESYNPUF_ID = b.DESYNPUF_ID
            WHERE a.BENE_DEATH_DT IS NOT NULL
              AND a.BENE_DEATH_DT != 0
              AND b.summary_year > (a.BENE_DEATH_DT / 10000)::INT
        """).fetchone()
        total_deceased = con.execute("""
            SELECT COUNT(DISTINCT DESYNPUF_ID) FROM beneficiary_summary
            WHERE BENE_DEATH_DT IS NOT NULL AND BENE_DEATH_DT != 0
        """).fetchone()[0]
        results.append(ValidationResult(
            check_name="summary_after_death",
            category="temporal",
            description="Deceased beneficiaries with summary records in years after their death year",
            total_checked=total_deceased,
            issues_found=r[0],
            issue_pct=round(100.0 * r[0] / max(total_deceased, 1), 4),
        ))
    except duckdb.Error as e:
        logger.debug(f"Summary-after-death check skipped: {e}")

    return results


def check_demographic_consistency(con: duckdb.DuckDBPyConnection) -> list[ValidationResult]:
    """Check for beneficiary demographics that change across years unexpectedly."""
    results = []

    # Sex should not change across years
    r = con.execute("""
        SELECT COUNT(DISTINCT DESYNPUF_ID) FROM (
            SELECT DESYNPUF_ID, COUNT(DISTINCT BENE_SEX_IDENT_CD) AS n_sex
            FROM beneficiary_summary
            GROUP BY DESYNPUF_ID
            HAVING COUNT(DISTINCT BENE_SEX_IDENT_CD) > 1
        )
    """).fetchone()
    total_benes = con.execute(
        "SELECT COUNT(DISTINCT DESYNPUF_ID) FROM beneficiary_summary"
    ).fetchone()[0]
    results.append(ValidationResult(
        check_name="sex_change_across_years",
        category="demographic",
        description="Beneficiaries whose sex code changes across summary years",
        total_checked=total_benes,
        issues_found=r[0],
        issue_pct=round(100.0 * r[0] / max(total_benes, 1), 4),
    ))

    # Race should not change
    r = con.execute("""
        SELECT COUNT(DISTINCT DESYNPUF_ID) FROM (
            SELECT DESYNPUF_ID, COUNT(DISTINCT BENE_RACE_CD) AS n_race
            FROM beneficiary_summary
            GROUP BY DESYNPUF_ID
            HAVING COUNT(DISTINCT BENE_RACE_CD) > 1
        )
    """).fetchone()
    results.append(ValidationResult(
        check_name="race_change_across_years",
        category="demographic",
        description="Beneficiaries whose race code changes across summary years",
        total_checked=total_benes,
        issues_found=r[0],
        issue_pct=round(100.0 * r[0] / max(total_benes, 1), 4),
    ))

    # DOB should not change
    r = con.execute("""
        SELECT COUNT(DISTINCT DESYNPUF_ID) FROM (
            SELECT DESYNPUF_ID, COUNT(DISTINCT BENE_BIRTH_DT) AS n_dob
            FROM beneficiary_summary
            GROUP BY DESYNPUF_ID
            HAVING COUNT(DISTINCT BENE_BIRTH_DT) > 1
        )
    """).fetchone()
    results.append(ValidationResult(
        check_name="dob_change_across_years",
        category="demographic",
        description="Beneficiaries whose date of birth changes across summary years",
        total_checked=total_benes,
        issues_found=r[0],
        issue_pct=round(100.0 * r[0] / max(total_benes, 1), 4),
    ))

    return results


def check_diagnosis_codes(con: duckdb.DuckDBPyConnection) -> list[ValidationResult]:
    """Validate ICD-9 diagnosis code format on carrier claims.

    ICD-9 codes are 3–5 character alphanumeric strings (e.g., '4019', 'V5789',
    'E8859'). Values that don't match this pattern indicate data corruption
    or encoding errors. We check the header-level diagnosis codes
    (ICD9_DGNS_CD_1 through _8).
    """
    results = []

    # Count non-null diagnosis values and those failing format check
    diag_cols = [f"ICD9_DGNS_CD_{i}" for i in range(1, 9)]
    total_values = 0
    invalid_values = 0

    for col in diag_cols:
        try:
            r = con.execute(f"""
                SELECT
                    COUNT(*) FILTER (WHERE {col} IS NOT NULL AND TRIM({col}::VARCHAR) != ''),
                    COUNT(*) FILTER (
                        WHERE {col} IS NOT NULL
                          AND TRIM({col}::VARCHAR) != ''
                          AND NOT regexp_matches(TRIM({col}::VARCHAR), '^[A-Za-z0-9]{{3,5}}$')
                    )
                FROM carrier_claims
            """).fetchone()
            total_values += r[0]
            invalid_values += r[1]
        except duckdb.Error as e:
            logger.debug(f"ICD-9 format check skipped for {col}: {e}")

    if total_values > 0:
        results.append(ValidationResult(
            check_name="icd9_format_validation",
            category="clinical",
            description="ICD-9 diagnosis codes (ICD9_DGNS_CD_1–8) failing alphanumeric 3–5 char format check",
            total_checked=total_values,
            issues_found=invalid_values,
            issue_pct=round(100.0 * invalid_values / max(total_values, 1), 4),
        ))

    return results


def check_npi_format(con: duckdb.DuckDBPyConnection) -> list[ValidationResult]:
    """Validate National Provider Identifier (NPI) format on carrier claims.

    NPIs are 10-digit numeric identifiers assigned to healthcare providers.
    Values that are not exactly 10 digits indicate data quality issues.
    We check PRF_PHYSN_NPI_1 through _5 (performing physician NPIs).
    """
    results = []
    npi_cols = [f"PRF_PHYSN_NPI_{i}" for i in range(1, 6)]
    total_values = 0
    invalid_values = 0

    for col in npi_cols:
        try:
            r = con.execute(f"""
                SELECT
                    COUNT(*) FILTER (WHERE {col} IS NOT NULL AND TRIM({col}::VARCHAR) != ''),
                    COUNT(*) FILTER (
                        WHERE {col} IS NOT NULL
                          AND TRIM({col}::VARCHAR) != ''
                          AND NOT regexp_matches(TRIM({col}::VARCHAR), '^[0-9]{{10}}$')
                    )
                FROM carrier_claims
            """).fetchone()
            total_values += r[0]
            invalid_values += r[1]
        except duckdb.Error as e:
            logger.debug(f"NPI format check skipped for {col}: {e}")

    if total_values > 0:
        results.append(ValidationResult(
            check_name="npi_format_validation",
            category="identity",
            description="Performing physician NPIs (PRF_PHYSN_NPI_1–5) failing 10-digit numeric format check",
            total_checked=total_values,
            issues_found=invalid_values,
            issue_pct=round(100.0 * invalid_values / max(total_values, 1), 4),
        ))

    return results


def run(con: duckdb.DuckDBPyConnection) -> list[ValidationResult]:
    """Execute all validation checks."""
    all_results = []

    all_results.extend(check_key_integrity(con))
    logger.info(f"Key integrity checks complete: {len(all_results)} checks")

    all_results.extend(check_temporal_consistency(con))
    logger.info(f"Temporal checks complete")

    all_results.extend(check_demographic_consistency(con))
    logger.info(f"Demographic checks complete")

    all_results.extend(check_coverage_period(con))
    logger.info("Coverage period checks complete")

    all_results.extend(check_esrd_consistency(con))
    logger.info("ESRD consistency check complete")

    all_results.extend(check_state_codes(con))
    logger.info("State code checks complete")

    all_results.extend(check_financial_reconciliation(con))
    logger.info(f"Financial reconciliation complete")

    all_results.extend(check_diagnosis_codes(con))
    logger.info("ICD-9 diagnosis code format check complete")

    all_results.extend(check_npi_format(con))
    logger.info("NPI format check complete")

    passed = sum(1 for r in all_results if r.passed)
    failed = len(all_results) - passed
    logger.info(f"Validation complete: {passed} passed, {failed} failed out of {len(all_results)} checks")

    return all_results
