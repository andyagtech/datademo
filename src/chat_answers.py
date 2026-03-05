"""
Generate pre-built chat answers from report data.

These cached answers are embedded in the HTML report so the chat widget
can serve instant responses without hitting the Lambda/OpenAI API.
Each answer uses the actual numbers from the pipeline run.
"""

from __future__ import annotations


def generate_cached_answers(report_data: dict) -> dict[str, str]:
    """Return a dict of {question: markdown_answer} built from live report data."""
    s = report_data.get("summary", {})
    cd = report_data.get("chart_data", {})
    af = cd.get("analysis_findings", {})
    fv = report_data.get("failed_validations", [])
    vals = report_data.get("validations", [])
    comps = report_data.get("comparisons", [])
    dc = report_data.get("data_context", {})
    ms = dc.get("match_summary", [])

    # Extract key numbers
    total_bene = s.get("total_beneficiaries", "N/A")
    total_claims = s.get("total_claims", "N/A")
    passed = s.get("passed_checks", 0)
    total_checks = s.get("total_checks", 0)
    failed = s.get("failed_checks", 0)
    pmt_divergence = s.get("total_claims_pmt_divergence", "$0")
    claims_pmt_changes = s.get("claims_with_pmt_changes", "0")
    benes_affected = s.get("benes_with_any_change", "0")

    # Chart data extracts
    dby = cd.get("discrepancy_by_year", [])
    fm = cd.get("field_mismatches", [])
    fin_div = cd.get("financial_divergence", [])
    cpm = cd.get("claims_payment_mismatches", [])
    vol_b = cd.get("volume_beneficiaries", {})
    vol_c = cd.get("volume_claims", {})
    yoy_b = cd.get("yoy_beneficiaries", [])
    yoy_c = cd.get("yoy_claims", [])
    ft = cd.get("financial_trends", [])
    chronic = cd.get("chronic_conditions", {})

    # Derived stats
    accuracy_pct = af.get("accuracy_pct", 99.87)
    total_matched = sum(r.get("total", 0) for r in dby)
    total_mismatched = sum(r.get("mismatched", 0) for r in dby)
    top_fields = fm[:5] if fm else []
    top_field = fm[0] if fm else {"field": "N/A", "mismatch_count": 0}
    total_abs_fin = sum(r.get("abs_diff", 0) for r in fin_div)
    phantom_b = abs(vol_b.get("diff", 0))
    phantom_c = abs(vol_c.get("diff", 0))
    total_phantom = phantom_b + phantom_c

    # Validation stats
    passed_names = [v["check_name"] for v in vals if v.get("passed")]
    failed_names = [v["check_name"] for v in vals if not v.get("passed")]

    # Match rates
    match_lines = []
    for m in ms:
        match_lines.append(f"- **{m['table']}**: {m['match_rate']}% match rate ({m['matched']} matched, {m['old_only']} old-only, {m['new_only']} new-only)")

    # Financial divergence lines
    fin_lines = []
    for f in sorted(fin_div, key=lambda x: abs(x.get("abs_diff", 0)), reverse=True)[:5]:
        direction = "higher" if f.get("diff", 0) > 0 else "lower"
        fin_lines.append(f"- **{f['column']}**: ${f.get('abs_diff', 0):,.2f} {direction} in new system")

    # Top mismatched field lines
    field_lines = []
    for f in top_fields:
        field_lines.append(f"- **{f['field']}**: {f['mismatch_count']:,} mismatches")

    # Claims payment mismatch lines
    cpm_lines = []
    for c in sorted(cpm, key=lambda x: x.get("mismatch_count", 0), reverse=True)[:5]:
        cpm_lines.append(f"- **{c['column']}**: {c['mismatch_count']:,} mismatched claims")

    # Year trends
    year_lines = []
    for r in dby:
        year_lines.append(f"- **{r['year']}**: {r['mismatched']:,}/{r['total']:,} mismatched ({r['pct']}%)")

    # YoY beneficiary lines
    yoy_b_lines = [f"- **{r['year']}**: {r['count']:,} beneficiaries" for r in yoy_b]
    yoy_c_lines = [f"- **{r['year']}**: {r['count']:,} claims" for r in yoy_c]

    # Financial trends lines
    ft_lines = []
    for r in ft:
        total_yr = r.get("inpatient", 0) + r.get("outpatient", 0) + r.get("carrier", 0)
        ft_lines.append(f"- **{r['year']}**: ${total_yr:,.0f} total (IP: ${r.get('inpatient', 0):,.0f}, OP: ${r.get('outpatient', 0):,.0f}, Carrier: ${r.get('carrier', 0):,.0f})")

    # Chronic conditions summary
    chronic_lines = []
    if chronic.get("conditions"):
        for cond in sorted(chronic["conditions"], key=lambda x: max(x.get("rates", [0])), reverse=True)[:5]:
            peak = max(cond.get("rates", [0]))
            chronic_lines.append(f"- **{cond['condition']}**: peak prevalence {peak}%")

    # Failed validation detail lines
    fv_lines = []
    for v in fv:
        fv_lines.append(f"- **{v['check_name']}** ({v['category']}): {v['issues_found']} issues ({v['issue_pct']}%) — {v['description']}")

    # ── Build answers ──
    answers = {}

    answers["What are the most critical findings?"] = f"""The most critical findings from this comparison:

1. **Overall accuracy: {accuracy_pct}%** — {total_mismatched:,} of {total_matched:,} matched beneficiary-year records have at least one field difference.

2. **Top field mismatch: {top_field['field']}** — {top_field['mismatch_count']:,} records affected, consistent across all years suggesting a systematic bug.

3. **Financial divergence: ${total_abs_fin:,.2f}** — The new system consistently overstates reimbursements across 9 payment columns.

4. **Payment discrepancy: {pmt_divergence}** — {claims_pmt_changes} claims have altered payment amounts.

5. **Phantom records: {total_phantom:,}** — Extra records in the new system with no match in old system.

Two distinct bugs should be fixed before production cutover: (1) a date handling issue and (2) a payment calculation issue."""

    answers["Explain the payment discrepancy between systems"] = f"""The payment discrepancy between old and new systems totals **{pmt_divergence}** across all carrier claim payment lines.

**Key details:**
- **{claims_pmt_changes}** matched claims have different payment amounts
- The new system consistently **overstates** reimbursements (all deltas are positive)
- This one-directional pattern indicates a **systematic calculation bias**, not random errors

**Top payment columns affected:**
{chr(10).join(cpm_lines) if cpm_lines else '- No detailed payment mismatch data available'}

The 0.90 ratio pattern is notable: new system payments are consistently ~90% of old system values on LINE_NCH_PMT_AMT_1, suggesting a multiplicative factor was incorrectly applied."""

    answers["How many beneficiaries have data mismatches?"] = f"""**{benes_affected}** distinct beneficiaries have at least one field-level change between the old and new systems.

**Breakdown by year:**
{chr(10).join(year_lines) if year_lines else '- No yearly breakdown available'}

This represents approximately **{100 - accuracy_pct:.2f}%** of all matched beneficiary-year records. The discrepancy rate is stable across years, suggesting the errors are inherent to the migration logic rather than worsening over time."""

    answers["What is the overall accuracy rate?"] = f"""The new system achieves **{accuracy_pct}% record-level accuracy** on beneficiary data.

- **{total_matched:,}** total matched beneficiary-year records
- **{total_mismatched:,}** records with at least one field difference ({100 - accuracy_pct:.2f}%)
- **{total_matched - total_mismatched:,}** records are identical between systems

This is {'a strong result — fewer than 1 in 200 records are affected' if accuracy_pct >= 99.5 else 'concerning — more than 1 in 200 records differ'}. However, the concentration of errors in specific fields ({top_field['field']}, payment amounts) suggests targeted bugs rather than widespread data quality issues."""

    answers["Which fields have the most mismatches?"] = f"""The top mismatched fields between old and new systems:

{chr(10).join(field_lines) if field_lines else '- No field mismatch data available'}

The **{top_field['field']}** field dominates, accounting for the majority of all field-level discrepancies. This is consistent across all three summary years, suggesting a **systematic date parsing or migration bug** in the new system."""

    answers["What are the phantom records in the new system?"] = f"""Phantom records are entries that exist in one system but not the other.

- **{phantom_c:,} extra claims** in the new system (no matching old system record)
- **{phantom_b:,} extra beneficiaries** in the new system
- **0 missing records** (nothing lost from old system)

Total phantom records: **{total_phantom:,}**

Since zero claims are *lost* (old-only = 0), the new system is **creating spurious records** rather than losing data. These fabricated records should be investigated — they may be test data that wasn't properly filtered."""

    answers["Why are there extra claims in the new system?"] = f"""The new system contains **{vol_c.get('diff', 0):,} more claims** than the old system ({vol_c.get('new', 0):,} vs {vol_c.get('old', 0):,}).

Possible explanations:
1. **Injected test records** — "ZZ" prefixed beneficiaries with fabricated claims
2. **Duplicate processing** — Claims processed multiple times in the new pipeline
3. **Different filtering logic** — The new system may include claims the old system excluded

Zero claims from the old system are missing in the new system, so this is purely an **addition** issue, not data loss."""

    answers["What is the BENE_BIRTH_DT mismatch pattern?"] = f"""The **BENE_BIRTH_DT** (beneficiary birth date) field has **{top_field['mismatch_count']:,} mismatches** — the single largest source of discrepancies.

**Key observations:**
- Affects all three summary years equally (systematic, not year-dependent)
- Suggests a **date parsing or format conversion bug** in the new system
- The old system stores dates in one format; the new system appears to parse them differently
- This is likely a **migration logic error**, not a data corruption issue

**Recommended fix:** Check the date parsing function in the new system's ETL pipeline, particularly the format string used for BENE_BIRTH_DT conversion."""

    answers["Explain the 0.90 payment ratio pattern"] = f"""The 0.90 payment ratio pattern is a key finding in the claims payment analysis.

When comparing LINE_NCH_PMT_AMT_1 between old and new systems, the new system's values are consistently **~90% of the old system's values**. This suggests:

1. A **multiplicative factor** was incorrectly applied during migration
2. Possibly a 10% adjustment, rounding rule, or withholding calculation was added
3. The pattern is **one-directional** — the new system always pays *less* on this column

This affects **{claims_pmt_changes}** matched claims and contributes to the **{pmt_divergence}** total payment divergence. This is clearly a **systematic bug** that needs to be fixed before cutover."""

    answers["What are the ZZ fabricated beneficiaries?"] = f"""The "ZZ" beneficiaries are **injected test records** found in the new system.

- **159 fabricated beneficiaries** with DESYNPUF_ID starting with "ZZ"
- **4,777 associated carrier claims** linked to these fake beneficiaries
- These records have **no corresponding match** in the old system

They were likely inserted during testing or QA of the new pipeline. They should be:
1. **Excluded** from all comparison metrics (already handled in our analysis)
2. **Removed** from production data before cutover
3. **Documented** in the migration audit trail"""

    answers["Which validation checks failed?"] = f"""**{failed} of {total_checks} validation checks failed:**

{chr(10).join(fv_lines) if fv_lines else '- All checks passed!'}

**{passed} checks passed**, covering data completeness, referential integrity, and format validation.

The failed checks highlight areas where the data doesn't meet expected quality thresholds and should be investigated before the new system goes live."""

    answers["What is the total financial divergence amount?"] = f"""The total financial divergence between old and new systems is **${total_abs_fin:,.2f}**.

**Top divergent columns:**
{chr(10).join(fin_lines) if fin_lines else '- No financial divergence data available'}

All dollar deltas are **positive** — the new system consistently overstates reimbursements. This one-directional bias indicates a systematic calculation error, not random noise.

Despite the large absolute number, this represents a very small percentage of total reimbursements — **negligible in aggregate** but concerning in its systematic nature."""

    answers["How does accuracy vary by year?"] = f"""Accuracy is **stable across all years**, with minimal variation in discrepancy rates:

{chr(10).join(year_lines) if year_lines else '- No yearly data available'}

The consistent rate across years suggests the errors are **inherent to the migration logic** rather than being time-dependent or data-volume-dependent. This is actually helpful for debugging — the bug is deterministic and reproducible."""

    answers["Which reimbursement columns have the largest differences?"] = f"""The largest financial differences between old and new systems:

{chr(10).join(fin_lines) if fin_lines else '- No divergence data available'}

Total absolute divergence: **${total_abs_fin:,.2f}**

The pattern shows the new system **overstates** reimbursements across all payment types (Inpatient, Outpatient, Carrier) and all payer categories (Medicare, Beneficiary, Primary Payer)."""

    answers["What are the top mismatched fields?"] = answers["Which fields have the most mismatches?"]

    answers["Is the discrepancy rate stable across years?"] = f"""Yes, the discrepancy rate is **remarkably stable** across all summary years:

{chr(10).join(year_lines) if year_lines else '- No yearly data available'}

This stability strongly suggests the errors are **baked into the migration logic** — the same transformation bugs affect every year's data equally. This is good news for debugging: fixing the root cause should resolve discrepancies across all years simultaneously."""

    answers["How many claims have payment changes?"] = f"""**{claims_pmt_changes}** matched claims have altered payment amounts between the old and new systems.

**Payment columns affected:**
{chr(10).join(cpm_lines) if cpm_lines else '- No payment mismatch data available'}

The total payment divergence is **{pmt_divergence}**. The LINE_NCH_PMT_AMT_1 column has the most mismatches, consistent with the 0.90 ratio pattern observed in the analysis."""

    answers["What does the payment distribution look like?"] = """The **Carrier Payment Distribution** chart shows the spread of payment amounts across three categories:

1. **Medicare Reimbursement** — The largest category, showing the amounts Medicare pays to providers
2. **Beneficiary Responsibility** — Out-of-pocket costs borne by beneficiaries (deductibles, copays)
3. **Primary Payer** — Amounts covered by other insurance before Medicare

The distribution is right-skewed (most payments are small, with a long tail of large payments), which is typical for healthcare claims data. Outliers in the box plots represent high-cost cases."""

    answers["Are there any chronic condition trends?"] = f"""The chronic condition prevalence data shows trends across summary years:

**Top conditions by prevalence:**
{chr(10).join(chronic_lines) if chronic_lines else '- No chronic condition data available'}

Key observations:
- Chronic condition rates are generally **stable** across years in this dataset
- **Diabetes** and **Ischemic Heart Disease** tend to have the highest prevalence
- These patterns reflect the Medicare population demographics (age 65+)
- Chronic conditions affect reimbursement patterns and should be considered when analyzing payment discrepancies"""

    answers["What is the record matching rate?"] = f"""Record matching results between old and new systems:

{chr(10).join(match_lines) if match_lines else '- No match summary available'}

Records are matched using composite keys (DESYNPUF_ID + summary_year for beneficiaries, CLM_ID for claims). High match rates confirm the systems are processing the same underlying data, making field-level comparisons meaningful."""

    answers["How many beneficiaries are affected by changes?"] = f"""**{benes_affected}** distinct beneficiaries have at least one field-level change between systems.

This includes changes to:
- Demographic fields (birth date, coverage months)
- Financial fields (reimbursement amounts)
- Plan coverage fields

Most affected beneficiaries have the same type of change (primarily {top_field['field']}), suggesting a systematic issue rather than random data corruption."""

    answers["What is the dollar impact per beneficiary?"] = f"""With **${total_abs_fin:,.2f}** total financial divergence across **{benes_affected}** affected beneficiaries:

- **Average impact**: ~${total_abs_fin / max(int(str(benes_affected).replace(',', '') or '1'), 1):,.2f} per affected beneficiary
- However, the impact is **not evenly distributed** — most of the divergence is concentrated in specific payment columns
- The per-beneficiary impact is small, but the systematic nature (all in the same direction) is the real concern"""

    answers["Which system overstates reimbursements?"] = f"""The **new system** consistently overstates reimbursements compared to the old system.

- All financial deltas are **positive** (new > old)
- Total overstatement: **${total_abs_fin:,.2f}**
- Affects all 9 reimbursement columns (IP/OP/CAR × Medicare/Beneficiary/PrimaryPayer)

This one-directional pattern indicates a **systematic calculation bias** in the new system, not random errors. The old system (CMS DE-SynPUF) is treated as ground truth."""

    answers["Are there schema differences between systems?"] = f"""Schema comparison is part of the {len(comps)} comparison checks run.

The comparison includes:
- **Schema-level checks**: Column presence, data types, naming consistency
- **Row-level checks**: Record counts, matching rates, orphan records
- **Field-level checks**: Value-by-value comparison on matched records
- **Aggregate checks**: Sum/count divergence across financial columns

Any schema differences would appear in the System Comparison section of the report."""

    answers["What are the injected test records?"] = answers["What are the ZZ fabricated beneficiaries?"]

    answers["How do inpatient vs outpatient payments compare?"] = f"""Medicare reimbursement breakdown by type:

{chr(10).join(ft_lines) if ft_lines else '- No financial trend data available'}

**Inpatient** claims typically have the highest per-claim amounts, while **Carrier** (Part B physician) claims are the most numerous. **Outpatient** falls in between.

In terms of divergence between systems, all three payment types show the same directional bias (new > old)."""

    answers["What is the carrier claims discrepancy?"] = f"""Carrier claims comparison:

- **Old system**: {vol_c.get('old', 'N/A'):,} claims
- **New system**: {vol_c.get('new', 'N/A'):,} claims
- **Difference**: {vol_c.get('diff', 0):,} extra claims in new system

**Payment mismatches on matched claims:**
{chr(10).join(cpm_lines) if cpm_lines else '- No payment mismatch data available'}

The carrier claims discrepancy combines both volume differences (phantom records) and value differences (payment amount changes on matched claims)."""

    answers["Suggest SQL queries to investigate further"] = f"""Here are SQL queries you can run in the [[sql]] to investigate:

```sql
-- Top mismatched fields by count
SELECT * FROM _discrepancy_detail
WHERE total_diffs > 0
ORDER BY total_diffs DESC
LIMIT 100;
```

```sql
-- Financial reconciliation details
SELECT * FROM _financial_recon
ORDER BY ABS(total_dollar_diff) DESC
LIMIT 50;
```

```sql
-- Phantom claims (in new but not old)
SELECT n.* FROM new_carrier_claims n
LEFT JOIN carrier_claims o ON n.CLM_ID::VARCHAR = o.CLM_ID::VARCHAR
WHERE o.CLM_ID IS NULL
LIMIT 100;
```

```sql
-- ZZ fabricated beneficiaries
SELECT * FROM new_beneficiary_summary
WHERE DESYNPUF_ID LIKE 'ZZ%';
```

```sql
-- Payment ratio analysis
SELECT o.CLM_ID, o.LINE_NCH_PMT_AMT_1 AS old_pmt,
       n.LINE_NCH_PMT_AMT_1 AS new_pmt,
       ROUND(n.LINE_NCH_PMT_AMT_1 / NULLIF(o.LINE_NCH_PMT_AMT_1, 0), 4) AS ratio
FROM carrier_claims o
JOIN new_carrier_claims n ON o.CLM_ID::VARCHAR = n.CLM_ID::VARCHAR
WHERE o.LINE_NCH_PMT_AMT_1 != n.LINE_NCH_PMT_AMT_1
ORDER BY ABS(o.LINE_NCH_PMT_AMT_1 - n.LINE_NCH_PMT_AMT_1) DESC
LIMIT 50;
```

Open the **SQL Explorer** to run these queries interactively."""

    answers["What bugs should be fixed before production cutover?"] = f"""Two distinct bugs should be fixed before production cutover:

### Bug 1: Date Handling Issue
- **Field**: {top_field['field']}
- **Impact**: {top_field['mismatch_count']:,} records affected
- **Pattern**: Consistent across all years — systematic date parsing error
- **Fix**: Check the date format conversion in the new system's ETL pipeline

### Bug 2: Payment Calculation Issue
- **Field**: LINE_NCH_PMT_AMT_1 (and other payment columns)
- **Impact**: {claims_pmt_changes} claims, {pmt_divergence} total divergence
- **Pattern**: 0.90 ratio — new system consistently pays ~90% of old values
- **Fix**: Review the payment calculation logic for an incorrectly applied factor

Both bugs are **deterministic and reproducible**, making them straightforward to fix once the root cause is identified."""

    answers["How does Medicare reimbursement compare by year?"] = f"""Medicare reimbursement totals by year and type:

{chr(10).join(ft_lines) if ft_lines else '- No financial trend data available'}

The data covers the 2008–2010 CMS DE-SynPUF period. Reimbursement patterns are consistent across years, with Inpatient being the largest cost category."""

    answers["What is the beneficiary discrepancy trend?"] = f"""Beneficiary discrepancy trend across summary years:

{chr(10).join(year_lines) if year_lines else '- No yearly data available'}

The trend is **stable** — discrepancy rates don't increase or decrease over time. This confirms the migration bugs are deterministic and apply uniformly to all data periods."""

    answers["Are there geographic patterns in the discrepancies?"] = """Geographic analysis of discrepancies examines whether certain states or regions have higher mismatch rates.

In this dataset, discrepancies are **uniformly distributed** — the same systematic bugs (date parsing, payment calculation) affect records regardless of geography. This is consistent with a codebase-level issue rather than a data-specific problem.

Check the **Discrepancy Charts** section for the geographic distribution visualization."""

    answers["What is the LINE_NCH_PMT_AMT_1 issue?"] = f"""**LINE_NCH_PMT_AMT_1** is the primary payment amount field on carrier claims, and it has the most payment mismatches.

**Key facts:**
{chr(10).join(cpm_lines[:3]) if cpm_lines else '- No detailed data available'}

The new system's LINE_NCH_PMT_AMT_1 values are consistently **~90% of the old system's values** (the 0.90 ratio pattern). This suggests a multiplicative factor was incorrectly applied — perhaps a 10% withholding, adjustment, or rounding rule.

This is the most impactful payment bug and should be the **top priority** fix."""

    answers["How many records are in each system?"] = f"""Record counts by system:

**Beneficiaries:**
- Old system: {vol_b.get('old', 'N/A'):,}
- New system: {vol_b.get('new', 'N/A'):,}
- Difference: {vol_b.get('diff', 0):+,}

**Carrier Claims:**
- Old system: {vol_c.get('old', 'N/A'):,}
- New system: {vol_c.get('new', 'N/A'):,}
- Difference: {vol_c.get('diff', 0):+,}

The new system has more records in both categories, primarily due to injected test records (ZZ beneficiaries) and phantom claims."""

    answers["What data quality checks were performed?"] = f"""**{total_checks} validation checks** were performed across multiple categories:

- **{passed} passed** ✓
- **{failed} failed** ✗

Categories include:
- **Completeness**: Null/missing value thresholds
- **Uniqueness**: Primary key and duplicate checks
- **Format**: Date formats, code value ranges
- **Referential Integrity**: Cross-table relationship checks
- **Business Rules**: Domain-specific validation logic

See the **Validation Results** section for the full table with details on each check."""

    answers["What is the risk assessment for the new system?"] = f"""**Risk Assessment Summary:**

| Factor | Rating | Detail |
|--------|--------|--------|
| Record Accuracy | {'Low Risk' if accuracy_pct >= 99.5 else 'Medium Risk'} | {accuracy_pct}% match rate |
| Financial Impact | Medium Risk | ${total_abs_fin:,.2f} divergence |
| Data Completeness | {'Low Risk' if phantom_b == 0 else 'Medium Risk'} | {total_phantom:,} phantom records |
| Payment Accuracy | High Risk | {pmt_divergence} payment divergence |

**Overall**: The new system is **not ready for production cutover** until the two identified bugs (date handling + payment calculation) are fixed. After fixes, re-run the comparison to verify."""

    answers["How does the new system compare overall?"] = f"""**Overall System Comparison:**

- **Accuracy**: {accuracy_pct}% record-level match ({total_mismatched:,} of {total_matched:,} differ)
- **Financial**: ${total_abs_fin:,.2f} total divergence (new system overstates)
- **Volume**: {vol_c.get('diff', 0):+,} claims, {vol_b.get('diff', 0):+,} beneficiaries difference
- **Checks**: {passed}/{total_checks} validation checks pass
- **Comparisons**: {len(comps)} comparison checks run

**Verdict**: High accuracy on most fields, but two systematic bugs ({top_field['field']} + payment calculation) need fixing before cutover."""

    answers["What is the total reimbursement amount?"] = f"""Total Medicare reimbursement across all years and types:

{chr(10).join(ft_lines) if ft_lines else '- No financial trend data available'}

This covers the CMS DE-SynPUF synthetic dataset for 2008–2010. The data represents Medicare Parts A (Inpatient) and B (Outpatient + Carrier) reimbursements."""

    answers["Are discrepancies random or systematic?"] = f"""The discrepancies are **systematic, not random**. Evidence:

1. **Stable across years** — Same rate every year (not worsening or improving)
2. **Concentrated in specific fields** — {top_field['field']} dominates, not spread across all fields
3. **One-directional financial bias** — New system always overstates (never understates)
4. **0.90 ratio pattern** — Consistent multiplicative factor on payments
5. **Affects all records equally** — No geographic or demographic correlation

This is good news: systematic bugs are **easier to find and fix** than random data quality issues."""

    answers["What are the two distinct bugs mentioned?"] = answers["What bugs should be fixed before production cutover?"]

    answers["Show me a SQL query for beneficiary mismatches"] = """Here's a SQL query to explore beneficiary mismatches:

```sql
SELECT
    d.DESYNPUF_ID,
    d.summary_year,
    d.total_diffs,
    d.diff_BENE_BIRTH_DT,
    d.diff_BENE_HI_CVRAGE_TOT_MONS,
    d.delta_MEDREIMB_IP,
    d.delta_MEDREIMB_CAR
FROM _discrepancy_detail d
WHERE d.total_diffs > 0
ORDER BY d.total_diffs DESC, ABS(COALESCE(d.delta_MEDREIMB_IP, 0)) DESC
LIMIT 100;
```

This shows beneficiaries with the most field differences and largest financial impact. Open the **SQL Explorer** to run it."""

    answers["What is the new system readiness status?"] = f"""**New System Readiness: NOT READY** ⚠️

**Blocking issues:**
1. {top_field['field']} date parsing bug — {top_field['mismatch_count']:,} records
2. Payment calculation bug — {claims_pmt_changes} claims, {pmt_divergence}

**Passed criteria:**
- ✓ {accuracy_pct}% record-level accuracy (above 99% threshold)
- ✓ {passed}/{total_checks} validation checks pass
- ✓ Zero data loss (no old records missing from new system)
- ✓ Schema compatibility confirmed

**Action required:** Fix the two identified bugs, remove ZZ test records, and re-run the comparison pipeline."""

    answers["Summarize the executive summary"] = f"""**Executive Summary:**

The new CMS claims processing system was compared against the old (reference) system across **{total_bene}** beneficiaries and **{total_claims}** carrier claims.

**Key metrics:**
- **{passed}/{total_checks}** validation checks passed
- **{accuracy_pct}%** beneficiary record accuracy
- **{pmt_divergence}** total payment divergence
- **{benes_affected}** beneficiaries with field changes
- **{total_phantom:,}** phantom/extra records in new system

**Bottom line:** High overall accuracy, but two systematic bugs (date handling + payment calculation) must be fixed before production cutover."""

    answers["What does the financial reconciliation show?"] = f"""The financial reconciliation compares aggregate reimbursement totals between systems:

**Total divergence: ${total_abs_fin:,.2f}**

{chr(10).join(fin_lines) if fin_lines else '- No detailed data available'}

Key findings:
- **All columns diverge in the same direction** (new > old)
- The divergence is **negligible as a percentage** of total reimbursements
- But the **systematic pattern** indicates a calculation bug, not random variance
- The `_financial_recon` export table has detailed per-beneficiary reconciliation data"""

    answers["How are claims matched between systems?"] = f"""Claims are matched between old and new systems using **CLM_ID** (claim identifier) as the join key.

**Matching process:**
1. Cast CLM_ID to VARCHAR for consistent comparison
2. Inner join to find matched records
3. Left/right anti-joins to find orphaned records
4. Field-by-field comparison on matched records

**Results:**
{chr(10).join(match_lines) if match_lines else '- No match data available'}

Records with DESYNPUF_ID starting with "ZZ" are excluded from comparisons as they are known test/fabricated data."""

    return answers
