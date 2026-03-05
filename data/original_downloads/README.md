# Original Downloads

Place old system **ZIP archives** here. The pipeline (Step 1: Receive & Verify)
automatically extracts them into `../old_system/` before ingestion.

> **Alternative:** If you already have the extracted CSVs, you can skip this folder
> entirely and place them directly in `../old_system/`. The pipeline checks for CSVs
> there first and only looks for ZIPs if none are found.

## Old System Files (required)

Download all 5 files for **Sample 1** from [CMS DE-SynPUF](https://www.cms.gov/data-research/statistics-trends-and-reports/medicare-claims-synthetic-public-use-files/cms-2008-2010-data-entrepreneurs-synthetic-public-use-file-de-synpuf/de10-sample-1):

| ZIP archive to download | Extracted CSV (placed in `../old_system/`) |
|--------------------------|-------------------------------------------|
| `*2008_Beneficiary_Summary_File_Sample_1.zip` | `DE1_0_2008_Beneficiary_Summary_File_Sample_1.csv` |
| `*2009_Beneficiary_Summary_File_Sample_1.zip` | `DE1_0_2009_Beneficiary_Summary_File_Sample_1.csv` |
| `*2010_Beneficiary_Summary_File_Sample_1.zip` | `DE1_0_2010_Beneficiary_Summary_File_Sample_1.csv` |
| `*Carrier_Claims_Sample_1A.zip` | `DE1_0_2008_to_2010_Carrier_Claims_Sample_1A.csv` |
| `*Carrier_Claims_Sample_1B.zip` | `DE1_0_2008_to_2010_Carrier_Claims_Sample_1B.csv` |

## New System Files (optional — for comparison)

| File | What to do |
|------|-----------|
| `New_Claims_System_Outputs.zip` | Extract into `../new_system/`: `unzip "New Claims System Outputs.zip" -d ../new_system/` |

The Docker entrypoint auto-detects CSVs in `../new_system/`. For local Python runs, pass `--new-data data/new_system/`.

## Data Lineage

```
original_downloads/*.zip (old)  →  Step 1: auto-extract  →  old_system/*.csv  →  Step 3: Ingest  →  database/cms_claims.duckdb
new_system/*.csv                ──────────────────────────────────────────────→  Step 3: Ingest  →  database/cms_claims.duckdb
```
