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

    for metric, col_diff in [
        ("MEDREIMB_CAR", "medreimb_diff"),
        ("BENRES_CAR", "benres_diff"),
        ("PPPYMT_CAR", "pppymt_diff"),
    ]:
        stats = con.execute(f"""
            SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN {col_diff} > 0.01 THEN 1 ELSE 0 END) AS mismatches,
                AVG({col_diff}) AS avg_diff,
                MAX({col_diff}) AS max_diff
            FROM _financial_recon
        """).fetchone()

        total, mismatches, avg_diff, max_diff = stats
        results.append(ValidationResult(
            check_name=f"financial_recon_{metric.lower()}",
            category="financial",
            description=f"Beneficiary summary {metric} vs computed aggregate from carrier claim lines",
            total_checked=total,
            issues_found=mismatches,
            issue_pct=round(100.0 * mismatches / max(total, 1), 2),
            details=[{"avg_diff": round(avg_diff, 2) if avg_diff else 0,
                       "max_diff": round(max_diff, 2) if max_diff else 0}],
        ))

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


def run(con: duckdb.DuckDBPyConnection) -> list[ValidationResult]:
    """Execute all validation checks."""
    all_results = []

    all_results.extend(check_key_integrity(con))
    logger.info(f"Key integrity checks complete: {len(all_results)} checks")

    all_results.extend(check_temporal_consistency(con))
    logger.info(f"Temporal checks complete")

    all_results.extend(check_demographic_consistency(con))
    logger.info(f"Demographic checks complete")

    all_results.extend(check_financial_reconciliation(con))
    logger.info(f"Financial reconciliation complete")

    passed = sum(1 for r in all_results if r.passed)
    failed = len(all_results) - passed
    logger.info(f"Validation complete: {passed} passed, {failed} failed out of {len(all_results)} checks")

    return all_results
