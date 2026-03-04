# Data Dictionary

> Overview of the CMS DE-SynPUF dataset used by this pipeline, including table schemas, column definitions, and guidance for using other samples.

---

## Table of Contents

1. [About the Dataset](#about-the-dataset)
2. [New System (Under Test)](#new-system-under-test)
3. [Beneficiary Summary Table](#beneficiary-summary-table)
4. [Carrier Claims Table](#carrier-claims-table)
5. [Schema Comparison: Old vs New](#schema-comparison-old-vs-new)
6. [Derived / Internal Tables](#derived--internal-tables)
7. [Using Other CMS Samples](#using-other-cms-samples)
8. [Codebook Reference](#codebook-reference)

---

## About the Dataset

**CMS DE-SynPUF** (Data Entrepreneurs' Synthetic Public Use File) is a synthetic Medicare claims dataset published by the Centers for Medicare & Medicaid Services (CMS). It was created to enable software development and research without exposing real patient data.

| Property | Value |
|---|---|
| **Publisher** | CMS (Centers for Medicare & Medicaid Services) |
| **Coverage** | Calendar years 2008, 2009, 2010 |
| **Population** | Synthetic Medicare beneficiaries (fee-for-service) |
| **Samples** | 20 independent samples (Sample 1 through Sample 20), each ~115K beneficiaries |
| **Download** | [cms.gov DE-SynPUF page](https://www.cms.gov/data-research/statistics-trends-and-reports/medicare-claims-synthetic-public-use-files/cms-2008-2010-data-entrepreneurs-synthetic-public-use-file-de-synpuf) |
| **Codebook** | [DE-SynPUF Codebook (PDF)](https://www.cms.gov/files/document/de-10-codebook.pdf) |

**How the data was synthesized:** CMS took real Medicare claims from 2008–2010, applied statistical disclosure limitation techniques (noise injection, field swapping, synthetic generation), and produced files that preserve the *statistical properties* of real data (distributions, correlations, claim patterns) without containing any actual patient records.

**What this pipeline uses:** Sample 1 only — 5 CSV files:

| File | Table | Records | Description |
|---|---|---|---|
| `DE1_0_2008_Beneficiary_Summary_File_Sample_1.csv` | `beneficiary_summary` | ~115K | Year 2008 beneficiary demographics + financials |
| `DE1_0_2009_Beneficiary_Summary_File_Sample_1.csv` | `beneficiary_summary` | ~115K | Year 2009 |
| `DE1_0_2010_Beneficiary_Summary_File_Sample_1.csv` | `beneficiary_summary` | ~113K | Year 2010 |
| `DE1_0_2008_to_2010_Carrier_Claims_Sample_1A.csv` | `carrier_claims` | ~2.37M | Carrier claims batch A |
| `DE1_0_2008_to_2010_Carrier_Claims_Sample_1B.csv` | `carrier_claims` | ~2.37M | Carrier claims batch B |

---

## New System (Under Test)

The new system is the replacement claims processing pipeline whose outputs are validated against the old system (ground truth). The new system data is provided as a password-protected zip file as part of the assessment.

**Source:** Assessment-provided zip file (password: `SlJxqMl9`)

### File Inventory

| File | DuckDB Table | Records | Size |
|---|---|---|---|
| `DE1_0_2008_Beneficiary_Summary_File_Sample_1_NEWSYSTEM.csv` | `new_beneficiary_summary` | ~116K | 14.6 MB |
| `DE1_0_2009_Beneficiary_Summary_File_Sample_1_NEWSYSTEM.csv` | `new_beneficiary_summary` | ~115K | 14.5 MB |
| `DE1_0_2010_Beneficiary_Summary_File_Sample_1_NEWSYSTEM.csv` | `new_beneficiary_summary` | ~113K | 14.1 MB |
| `DE1_0_2008_to_2010_Carrier_Claims_Sample_1A_NEWSYSTEM.csv` | `new_carrier_claims` | ~2.37M | 1.24 GB |
| `DE1_0_2008_to_2010_Carrier_Claims_Sample_1B_NEWSYSTEM.csv` | `new_carrier_claims` | ~2.37M | 1.24 GB |

### Key Observations

The new system intentionally contains issues. At a high level:

- **Same file structure** as the old system — 3 beneficiary summary files (one per year) + 2 carrier claims files
- **Same column names** — all 33 beneficiary columns and 142 carrier claims columns are present
- **Row count differences** — the new system produces 4,777 more carrier claims than the old system (phantom claims that exist only in the new system)
- **One type difference** — `CLM_ID` is `BIGINT` in the old system and `VARCHAR` in the new system (handled automatically by DuckDB during matching via cast)
- **Intentional data discrepancies** — detailed in the [Schema Comparison](#schema-comparison-old-vs-new) section below

The pipeline auto-detects these files by reading CSV headers — the `_NEWSYSTEM` filename suffix is not required.

---

## Beneficiary Summary Table

**DuckDB table name:** `beneficiary_summary` (old system), `new_beneficiary_summary` (new system)

**Grain:** One row per beneficiary per calendar year.

**Primary key:** `(DESYNPUF_ID, summary_year)`

| Column | Type | Description | Example |
|---|---|---|---|
| `DESYNPUF_ID` | VARCHAR | Unique beneficiary identifier (16-char hex) | `00013D2EFD8E45D1` |
| `summary_year` | INTEGER | Calendar year (derived from filename during ingestion) | `2008` |
| `BENE_BIRTH_DT` | INTEGER | Date of birth (YYYYMMDD format) | `19230501` |
| `BENE_DEATH_DT` | INTEGER | Date of death, 0 if alive (YYYYMMDD) | `0` or `20090715` |
| `BENE_SEX_IDENT_CD` | INTEGER | Sex: 1 = Male, 2 = Female | `1` |
| `BENE_RACE_CD` | INTEGER | Race: 1=White, 2=Black, 3=Other, 5=Hispanic | `1` |
| `SP_STATE_CODE` | INTEGER | State SSA code (1–53) | `26` |
| `BENE_COUNTY_CD` | INTEGER | County SSA code | `999` |
| `BENE_HI_CVRAGE_TOT_MONS` | INTEGER | Months of Part A (Hospital Insurance) coverage | `12` |
| `BENE_SMI_CVRAGE_TOT_MONS` | INTEGER | Months of Part B (Supplementary Medical Insurance) coverage | `12` |
| `BENE_HMO_CVRAGE_TOT_MONS` | INTEGER | Months of HMO coverage | `0` |
| `PLAN_CVRG_MOS_NUM` | INTEGER | Months of Part D (prescription drug) coverage | `12` |

### Chronic Condition Flags

Each flag is `1` (condition present) or `2` (absent/unknown). The pipeline checks value `1` for prevalence.

| Column | Condition |
|---|---|
| `SP_ALZHDMTA` | Alzheimer's Disease / Related Dementia |
| `SP_CHF` | Heart Failure |
| `SP_CHRNKIDN` | Chronic Kidney Disease |
| `SP_CNCR` | Cancer (Breast, Colorectal, Prostate, Lung, Endometrial) |
| `SP_COPD` | Chronic Obstructive Pulmonary Disease |
| `SP_DEPRESSN` | Depression |
| `SP_DIABETES` | Diabetes |
| `SP_ISCHMCHT` | Ischemic Heart Disease |
| `SP_OSTEOPRS` | Osteoporosis |
| `SP_RA_OA` | Rheumatoid Arthritis / Osteoarthritis |
| `SP_STRKETIA` | Stroke / Transient Ischemic Attack |

### Financial Summary Columns

Annual reimbursement totals per beneficiary, broken down by service type. These should reconcile with the sum of individual claim line items (validated by the financial reconciliation checks).

| Column | Description |
|---|---|
| `MEDREIMB_IP` | Medicare reimbursement — Inpatient |
| `BENRES_IP` | Beneficiary responsibility — Inpatient |
| `PPPYMT_IP` | Primary payer payment — Inpatient |
| `MEDREIMB_OP` | Medicare reimbursement — Outpatient |
| `BENRES_OP` | Beneficiary responsibility — Outpatient |
| `PPPYMT_OP` | Primary payer payment — Outpatient |
| `MEDREIMB_CAR` | Medicare reimbursement — Carrier |
| `BENRES_CAR` | Beneficiary responsibility — Carrier |
| `PPPYMT_CAR` | Primary payer payment — Carrier |

**Financial reconciliation formula (per codebook):**
```
MEDREIMB_CAR = SUM(LINE_NCH_PMT_AMT) for lines where:
  LINE_PRCSG_IND_CD = 'A'
  OR (LINE_PRCSG_IND_CD IN ('R','S') AND LINE_ALOWD_CHRG_AMT > 0)

BENRES_CAR = SUM(LINE_BENE_PTB_DDCTBL_AMT + LINE_COINSRNC_AMT) [same filter]
PPPYMT_CAR = SUM(LINE_BENE_PRMRY_PYR_PD_AMT) [same filter]
```

---

## Carrier Claims Table

**DuckDB table name:** `carrier_claims` (old system), `new_carrier_claims` (new system)

**Grain:** One row per carrier claim. Each claim can have up to 13 line items (denormalized — line item columns are suffixed `_1` through `_13`).

**Primary key:** `CLM_ID`

### Claim Header Columns

| Column | Type | Description | Example |
|---|---|---|---|
| `DESYNPUF_ID` | VARCHAR | Beneficiary ID (FK to beneficiary_summary) | `00013D2EFD8E45D1` |
| `CLM_ID` | BIGINT/VARCHAR | Unique claim identifier | `196661176960050` |
| `CLM_FROM_DT` | INTEGER | Claim start date (YYYYMMDD) | `20090812` |
| `CLM_THRU_DT` | INTEGER | Claim end date (YYYYMMDD) | `20090812` |
| `ICD9_DGNS_CD_1` through `_8` | VARCHAR | ICD-9 diagnosis codes (up to 8) | `4019` |
| `PRF_PHYSN_NPI_1`, `_2` | VARCHAR | Performing physician NPI | `0000000000` |
| `TAX_NUM_1` through `_13` | VARCHAR | Provider tax number per line | |

### Claim Line Columns (×13)

Each of the following columns is repeated 13 times with suffix `_1` through `_13`:

| Column Pattern | Type | Description |
|---|---|---|
| `LINE_NCH_PMT_AMT_{n}` | DOUBLE | Medicare payment amount for this line |
| `LINE_BENE_PTB_DDCTBL_AMT_{n}` | DOUBLE | Beneficiary Part B deductible |
| `LINE_COINSRNC_AMT_{n}` | DOUBLE | Beneficiary coinsurance amount |
| `LINE_ALOWD_CHRG_AMT_{n}` | DOUBLE | Allowed charge amount |
| `LINE_BENE_PRMRY_PYR_PD_AMT_{n}` | DOUBLE | Primary payer payment |
| `LINE_PRCSG_IND_CD_{n}` | VARCHAR | Processing indicator: A=Allowed, R=Rejected, S=Secondary |
| `LINE_ICD9_DGNS_CD_{n}` | VARCHAR | Line-level ICD-9 diagnosis code |
| `HCPCS_CD_{n}` | VARCHAR | HCPCS procedure code |
| `LINE_PLACE_OF_SRVC_CD_{n}` | VARCHAR | Place of service code |

**Why 142 columns:** 8 diagnosis codes + 2 NPIs + 13 tax numbers + (13 lines × 9 columns per line) = 142 total. This is a denormalized layout — a normalized design would have a separate `claim_lines` table.

---

## Schema Comparison: Old vs New

The pipeline's Step 2 (Schema Validate) and Step 5 (Compare) verify schema compatibility. Here is the full comparison:

### Beneficiary Summary

| Property | Old System | New System | Match? |
|---|---|---|---|
| **Column count** | 33 | 33 | ✅ Identical |
| **Column names** | All 33 present | All 33 present | ✅ Identical |
| **Column types** | All match | All match | ✅ Identical |
| **Row count** | 343,644 | 343,644 | ✅ Identical |
| **Unique beneficiaries** | ~115K | ~115K | ✅ (3 years × ~115K) |

### Carrier Claims

| Property | Old System | New System | Match? |
|---|---|---|---|
| **Column count** | 142 | 142 | ✅ Identical |
| **Column names** | All 142 present | All 142 present | ✅ Identical |
| **CLM_ID type** | `BIGINT` | `VARCHAR` | ⚠️ Type mismatch — cast during match |
| **Row count** | 4,741,335 | 4,746,112 | ❌ +4,777 new-only (phantom claims) |

### Discrepancies Found by the Pipeline

| Category | Count | Description |
|---|---|---|
| **Beneficiary field mismatches** | 446 records | At least one field differs between old and new |
| **BENE_BIRTH_DT mismatches** | 178 | Largest single field — systematic date parsing bug |
| **Financial column mismatches** | 47–46 per column | MEDREIMB_OP, BENRES_CAR, PPPYMT_CAR, etc. |
| **Claims payment mismatches** | 10,411 on LINE_NCH_PMT_AMT_1 | Primary payment amount — systematic calculation error |
| **Phantom claims** | 4,777 | Exist in new system only, 0 lost from old system |
| **Total financial divergence** | $35,624.71 | All positive (new system overstates) |

For the full analysis of what these discrepancies mean, see the [Key Findings narrative](../reports/comparison_report.html) in the HTML report and the [Analysis Findings](../specs/SOLUTION.md#analysis-findings) section in SOLUTION.md.

---

## Derived / Internal Tables

These tables are created by the pipeline during execution and are available for querying in the DuckDB database.

| Table | Created By | Grain | Description |
|---|---|---|---|
| `_match_beneficiary` | Step 4 | One row per unique beneficiary-year key | FULL OUTER JOIN result: `match_status` = matched / old_only / new_only |
| `_match_claims` | Step 4 | One row per unique CLM_ID | FULL OUTER JOIN result for claims |
| `_discrepancy_detail` | Step 5 | One row per matched beneficiary-year | Field-by-field diff flags (`diff_*`), dollar deltas (`delta_*`), and `total_diffs` count |
| `_financial_recon` | Validation | One row per beneficiary-year with claims | Reported vs. computed financial amounts from claim line aggregation |

### `_discrepancy_detail` Columns

| Column | Type | Description |
|---|---|---|
| `DESYNPUF_ID` | VARCHAR | Beneficiary ID |
| `summary_year` | INTEGER | Calendar year |
| `SP_STATE_CODE` | INTEGER | State code (for geographic analysis) |
| `diff_{field}` | INTEGER (0/1) | 1 if old value ≠ new value for this field |
| `delta_{financial_field}` | DOUBLE | Dollar difference (new − old) for financial columns |
| `total_diffs` | INTEGER | Count of fields with mismatches for this record |

---

## Using Other CMS Samples

The pipeline is designed to work with **any DE-SynPUF sample** (1–20). To use a different sample:

1. **Download** the desired sample files from the [CMS DE-SynPUF page](https://www.cms.gov/data-research/statistics-trends-and-reports/medicare-claims-synthetic-public-use-files/cms-2008-2010-data-entrepreneurs-synthetic-public-use-file-de-synpuf).

2. **Place the CSVs** in `data/raw/`:
   ```bash
   mkdir -p data/raw
   # Unzip the downloaded files
   for f in *.zip; do unzip -o "$f" -d data/raw/; done
   ```

3. **Run the pipeline** — file detection is automatic (matches glob patterns `*Beneficiary*` and `*Carrier*`):
   ```bash
   python -m src.main
   ```

4. **For new system comparison**, place the comparison CSVs in a separate directory:
   ```bash
   python -m src.main --new-data path/to/new/csvs/
   ```

**Compatibility notes:**
- All 20 samples share the same schema (column names and types are identical).
- Sample sizes are roughly equal (~115K beneficiaries, ~4.7M claims per sample).
- Samples are independent — different synthetic beneficiaries, no overlap.
- The pipeline auto-detects file types from CSV headers, so filenames can vary.

### Extending to Non-CMS Data

The pipeline can be adapted for other paired-CSV comparison use cases. The key requirements:
- Both systems produce CSVs with overlapping schemas.
- There is a joinable primary key across systems.
- Configuration changes needed: `TABLE_PAIRS` in `src/compare.py` (column lists) and `KEY_CONFIG` in `src/pipeline/step4_match.py` (join keys).

---

## Codebook Reference

The CMS DE-SynPUF Codebook provides the authoritative definitions for all columns, value codes, and business rules. Key sections used by this pipeline:

| Codebook Section | Pipeline Usage |
|---|---|
| **Table 1: Beneficiary Summary** | Column definitions, chronic condition flag values (1 = yes, 2 = no) |
| **Table 4: Carrier Claims** | Claim structure, line item layout, processing indicator codes |
| **Financial Reconciliation Rules** | How `MEDREIMB_CAR` is computed from `LINE_NCH_PMT_AMT` with `LINE_PRCSG_IND_CD` filter |
| **SSA State Codes** | Mapping of `SP_STATE_CODE` to U.S. states (used in geographic analysis) |

**Download:** [DE-SynPUF Codebook (PDF)](https://www.cms.gov/files/document/de-10-codebook.pdf)
