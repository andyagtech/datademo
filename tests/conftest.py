"""
Shared test fixtures — creates small in-memory DuckDB tables
that mirror the real schema for isolated, fast testing.
"""

import pytest
import duckdb


@pytest.fixture
def con():
    """In-memory DuckDB connection with sample legacy data loaded."""
    c = duckdb.connect(":memory:")

    # Beneficiary summary — 4 beneficiaries across 2 years
    c.execute("""
        CREATE TABLE beneficiary_summary AS
        SELECT * FROM (VALUES
            ('BENE_A', 19500101, 0,          1, 1, 0, 26, 950, 12, 12, 0, 12, 1, 2, 1, 1, 1, 1, 1, 1, 1, 1, 1, 100, 20, 5, 200, 30, 10, 300.0, 40.0, 15.0, 2008),
            ('BENE_A', 19500101, 0,          1, 1, 0, 26, 950, 12, 12, 0, 12, 1, 2, 1, 1, 1, 1, 1, 1, 1, 1, 1, 110, 22, 6, 210, 32, 11, 310.0, 42.0, 16.0, 2009),
            ('BENE_B', 19400301, 20080615,   2, 2, 0, 10, 100, 12, 12, 0, 12, 2, 1, 2, 2, 2, 2, 2, 2, 2, 2, 2, 50,  10, 3, 60,  12, 4,  80.0,  18.0, 7.0,  2008),
            ('BENE_C', 19600715, 0,          1, 3, 0, 05, 200, 12, 12, 0, 12, 1, 1, 1, 2, 1, 2, 1, 2, 1, 2, 1, 0,   0,  0, 0,   0,  0,  0.0,   0.0,  0.0,  2008),
            ('BENE_D', 19550901, 0,          2, 1, 0, 36, 300, 12, 12, 0, 12, 2, 2, 2, 1, 2, 1, 2, 1, 2, 1, 2, 200, 40, 10, 300, 50, 20, 500.0, 60.0, 25.0, 2008)
        ) AS t(
            DESYNPUF_ID, BENE_BIRTH_DT, BENE_DEATH_DT, BENE_SEX_IDENT_CD, BENE_RACE_CD,
            BENE_ESRD_IND, SP_STATE_CODE, BENE_COUNTY_CD, BENE_HI_CVRAGE_TOT_MONS,
            BENE_SMI_CVRAGE_TOT_MONS, BENE_HMO_CVRAGE_TOT_MONS, PLAN_CVRG_MOS_NUM,
            SP_ALZHDMTA, SP_CHF, SP_CHRNKIDN, SP_CNCR, SP_COPD, SP_DEPRESSN,
            SP_DIABETES, SP_ISCHMCHT, SP_OSTEOPRS, SP_RA_OA, SP_STRKETIA,
            MEDREIMB_IP, BENRES_IP, PPPYMT_IP, MEDREIMB_OP, BENRES_OP, PPPYMT_OP,
            MEDREIMB_CAR, BENRES_CAR, PPPYMT_CAR, summary_year
        )
    """)

    # Carrier claims — build with all 142 columns (13 line items)
    # We'll create a minimal set with key columns and line-item columns
    line_cols = []
    for i in range(1, 14):
        line_cols.extend([
            f"PRF_PHYSN_NPI_{i}", f"TAX_NUM_{i}", f"HCPCS_CD_{i}",
            f"LINE_NCH_PMT_AMT_{i}", f"LINE_BENE_PTB_DDCTBL_AMT_{i}",
            f"LINE_BENE_PRMRY_PYR_PD_AMT_{i}", f"LINE_COINSRNC_AMT_{i}",
            f"LINE_ALOWD_CHRG_AMT_{i}", f"LINE_PRCSG_IND_CD_{i}",
            f"LINE_ICD9_DGNS_CD_{i}",
        ])

    # Create table with the proper schema first
    create_cols = [
        "DESYNPUF_ID VARCHAR", "CLM_ID BIGINT", "CLM_FROM_DT BIGINT", "CLM_THRU_DT BIGINT",
    ]
    for i in range(1, 9):
        create_cols.append(f"ICD9_DGNS_CD_{i} VARCHAR")
    for i in range(1, 14):
        create_cols.append(f"PRF_PHYSN_NPI_{i} VARCHAR")
    for i in range(1, 14):
        create_cols.append(f"TAX_NUM_{i} VARCHAR")
    for i in range(1, 14):
        create_cols.append(f"HCPCS_CD_{i} VARCHAR")
    for i in range(1, 14):
        create_cols.append(f"LINE_NCH_PMT_AMT_{i} DOUBLE")
    for i in range(1, 14):
        create_cols.append(f"LINE_BENE_PTB_DDCTBL_AMT_{i} DOUBLE")
    for i in range(1, 14):
        create_cols.append(f"LINE_BENE_PRMRY_PYR_PD_AMT_{i} DOUBLE")
    for i in range(1, 14):
        create_cols.append(f"LINE_COINSRNC_AMT_{i} DOUBLE")
    for i in range(1, 14):
        create_cols.append(f"LINE_ALOWD_CHRG_AMT_{i} DOUBLE")
    for i in range(1, 14):
        create_cols.append(f"LINE_PRCSG_IND_CD_{i} VARCHAR")
    for i in range(1, 14):
        create_cols.append(f"LINE_ICD9_DGNS_CD_{i} VARCHAR")

    c.execute(f"CREATE TABLE carrier_claims ({', '.join(create_cols)})")

    # Insert test claims
    # BENE_A: 2 claims in 2008, with known payment amounts for reconciliation
    # BENE_B: 1 claim AFTER death (temporal issue)
    # BENE_D: 1 claim with date inversion
    # ORPHAN: 1 claim for non-existent beneficiary

    def _insert_claim(bene_id, clm_id, from_dt, thru_dt, pmt1=0, ddctbl1=0, coinsrnc1=0, prmry1=0, alowd1=0, prcsg1='A',
                       icd9_1=None, icd9_2=None, npi_1=None):
        null_cols_count = len(create_cols) - 4  # minus the 4 base cols
        vals = [f"'{bene_id}'", str(clm_id), str(from_dt), str(thru_dt)]
        # ICD9 diags (8)
        vals.append(f"'{icd9_1}'" if icd9_1 else "NULL")
        vals.append(f"'{icd9_2}'" if icd9_2 else "NULL")
        vals.extend(["NULL"] * 6)
        # PRF_PHYSN_NPI (13)
        vals.append(f"'{npi_1}'" if npi_1 else "NULL")
        vals.extend(["NULL"] * 12)
        # TAX_NUM (13)
        vals.extend(["NULL"] * 13)
        # HCPCS_CD (13)
        vals.extend(["NULL"] * 13)
        # LINE_NCH_PMT_AMT (13) — set first, rest null
        vals.append(str(pmt1))
        vals.extend(["NULL"] * 12)
        # LINE_BENE_PTB_DDCTBL_AMT (13)
        vals.append(str(ddctbl1))
        vals.extend(["NULL"] * 12)
        # LINE_BENE_PRMRY_PYR_PD_AMT (13)
        vals.append(str(prmry1))
        vals.extend(["NULL"] * 12)
        # LINE_COINSRNC_AMT (13)
        vals.append(str(coinsrnc1))
        vals.extend(["NULL"] * 12)
        # LINE_ALOWD_CHRG_AMT (13)
        vals.append(str(alowd1))
        vals.extend(["NULL"] * 12)
        # LINE_PRCSG_IND_CD (13)
        vals.append(f"'{prcsg1}'")
        vals.extend(["NULL"] * 12)
        # LINE_ICD9_DGNS_CD (13)
        vals.extend(["NULL"] * 13)
        c.execute(f"INSERT INTO carrier_claims VALUES ({', '.join(vals)})")

    # BENE_A claims in 2008 (should sum to MEDREIMB_CAR=300)
    _insert_claim('BENE_A', 1001, 20080101, 20080101, pmt1=150, ddctbl1=20, coinsrnc1=20, prmry1=7.5, alowd1=200, prcsg1='A',
                  icd9_1='4019', icd9_2='25000', npi_1='1234567890')
    _insert_claim('BENE_A', 1002, 20080601, 20080601, pmt1=150, ddctbl1=20, coinsrnc1=20, prmry1=7.5, alowd1=200, prcsg1='A',
                  icd9_1='V5789', npi_1='1234567890')
    # BENE_A claim in 2009
    _insert_claim('BENE_A', 1003, 20090301, 20090301, pmt1=310, ddctbl1=22, coinsrnc1=20, prmry1=16, alowd1=400, prcsg1='A',
                  icd9_1='4019', npi_1='9876543210')
    # BENE_B claim AFTER death (death=20080615, claim=20080901)
    _insert_claim('BENE_B', 2001, 20080901, 20080901, pmt1=80, ddctbl1=10, coinsrnc1=8, prmry1=7, alowd1=100, prcsg1='A',
                  icd9_1='E8859', npi_1='1111111111')
    # BENE_D claim with date inversion (from > thru)
    _insert_claim('BENE_D', 4001, 20080815, 20080801, pmt1=500, ddctbl1=30, coinsrnc1=30, prmry1=25, alowd1=600, prcsg1='A',
                  icd9_1='4019', npi_1='2222222222')
    # ORPHAN claim (bene not in summary)
    _insert_claim('ORPHAN_X', 9001, 20080501, 20080501, pmt1=50, ddctbl1=5, coinsrnc1=5, prmry1=2, alowd1=60, prcsg1='A',
                  icd9_1='4019', npi_1='3333333333')

    return c


@pytest.fixture
def con_with_new(con):
    """Extend the base fixture with a 'new system' table for comparison tests."""
    # New beneficiary summary — same schema, some differences
    con.execute("""
        CREATE TABLE new_beneficiary_summary AS
        SELECT * FROM (VALUES
            ('BENE_A', 19500101, 0,          1, 1, 0, 26, 950, 12, 12, 0, 12, 1, 2, 1, 1, 1, 1, 1, 1, 1, 1, 1, 100, 20, 5, 200, 30, 10, 305.0, 40.0, 15.0, 2008),
            ('BENE_A', 19500101, 0,          1, 1, 0, 26, 950, 12, 12, 0, 12, 1, 2, 1, 1, 1, 1, 1, 1, 1, 1, 1, 110, 22, 6, 210, 32, 11, 310.0, 42.0, 16.0, 2009),
            ('BENE_B', 19400301, 20080615,   2, 2, 0, 10, 100, 12, 12, 0, 12, 2, 1, 2, 2, 2, 2, 2, 2, 2, 2, 2, 50,  10, 3, 60,  12, 4,  80.0,  18.0, 7.0,  2008),
            ('BENE_C', 19600715, 0,          1, 5, 0, 05, 200, 12, 12, 0, 12, 1, 1, 1, 2, 1, 2, 1, 2, 1, 2, 1, 0,   0,  0, 0,   0,  0,  0.0,   0.0,  0.0,  2008),
            ('BENE_NEW', 19700101, 0,        1, 1, 0, 12, 400, 12, 12, 0, 12, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 50,  10, 2, 30,  8,  3,  70.0,  12.0, 5.0,  2008)
        ) AS t(
            DESYNPUF_ID, BENE_BIRTH_DT, BENE_DEATH_DT, BENE_SEX_IDENT_CD, BENE_RACE_CD,
            BENE_ESRD_IND, SP_STATE_CODE, BENE_COUNTY_CD, BENE_HI_CVRAGE_TOT_MONS,
            BENE_SMI_CVRAGE_TOT_MONS, BENE_HMO_CVRAGE_TOT_MONS, PLAN_CVRG_MOS_NUM,
            SP_ALZHDMTA, SP_CHF, SP_CHRNKIDN, SP_CNCR, SP_COPD, SP_DEPRESSN,
            SP_DIABETES, SP_ISCHMCHT, SP_OSTEOPRS, SP_RA_OA, SP_STRKETIA,
            MEDREIMB_IP, BENRES_IP, PPPYMT_IP, MEDREIMB_OP, BENRES_OP, PPPYMT_OP,
            MEDREIMB_CAR, BENRES_CAR, PPPYMT_CAR, summary_year
        )
    """)
    # Differences vs old:
    #   BENE_A 2008: MEDREIMB_CAR 300 -> 305 (financial mismatch)
    #   BENE_C: BENE_RACE_CD 3 -> 5 (field mismatch)
    #   BENE_D: missing entirely (row-level)
    #   BENE_NEW: extra in new (row-level)

    return con
