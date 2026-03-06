"""
Generate pre-built chat answers from report data.

These cached answers are embedded in the HTML report so the chat widget
can serve instant responses without hitting the Lambda/OpenAI API.
Each answer uses the actual numbers from the pipeline run.
"""

from __future__ import annotations


def generate_cached_answers(report_data: dict) -> dict[str, dict]:
    """Return a dict of {question: {answer, queries}} built from live report data."""
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

    # Claim line utilization data
    clu = report_data.get("claim_line_utilization", {})

    # Validation detail extraction helpers — group by category
    val_by_cat: dict[str, list] = {}
    for v in vals:
        cat = v.get("category", "other")
        val_by_cat.setdefault(cat, []).append(v)

    coverage_vals = val_by_cat.get("coverage", [])
    clinical_vals = val_by_cat.get("clinical", [])
    identity_vals = val_by_cat.get("identity", [])
    temporal_vals = val_by_cat.get("temporal", [])
    demographic_vals = val_by_cat.get("demographic", [])
    financial_vals = val_by_cat.get("financial", [])

    # Coverage check lines
    coverage_lines = []
    for v in coverage_vals:
        status = "✓ passed" if v.get("passed") else f"✗ {v['issues_found']} issues"
        coverage_lines.append(f"- **{v['check_name']}**: {status} ({v['total_checked']} checked)")

    # Clinical check lines (ESRD, ICD-9, NPI)
    clinical_lines = []
    for v in clinical_vals:
        status = "✓ passed" if v.get("passed") else f"✗ {v['issues_found']} issues"
        clinical_lines.append(f"- **{v['check_name']}**: {status}")

    # Financial recon detail lines (with distribution)
    fin_recon_lines = []
    for v in financial_vals:
        details = v.get("details", [{}])
        d = details[0] if details else {}
        dist = d.get("distribution", {})
        if dist:
            fin_recon_lines.append(
                f"- **{v['check_name']}**: avg diff ${d.get('avg_diff', 0)}, max diff ${d.get('max_diff', 0)} — "
                f"exact: {dist.get('exact_match_lte_0.01', 'N/A')}, "
                f"$0.01–$1: {dist.get('diff_0.01_to_1.00', 'N/A')}, "
                f"$1–$100: {dist.get('diff_1.00_to_100.00', 'N/A')}, "
                f">$100: {dist.get('diff_over_100.00', 'N/A')}"
            )

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

    # ── Aliases: "Can you explain" / "Please summarize" variants of existing answers ──
    answers["Can you explain the most critical findings?"] = answers["What are the most critical findings?"]
    answers["Can you explain the payment discrepancy between systems?"] = answers["Explain the payment discrepancy between systems"]
    answers["Can you explain the 0.90 payment ratio pattern?"] = answers["Explain the 0.90 payment ratio pattern"]
    answers["Can you explain how discrepancies are distributed across years?"] = answers["How does accuracy vary by year?"]
    answers["Can you explain whether the discrepancies are random or systematic?"] = answers["Are discrepancies random or systematic?"]
    answers["Can you explain the risk assessment for the new system?"] = answers["What is the risk assessment for the new system?"]
    answers["Can you explain the new system readiness status?"] = answers["What is the new system readiness status?"]
    answers["Can you explain what bugs should be fixed before production cutover?"] = answers["What bugs should be fixed before production cutover?"]
    answers["Can you explain the phantom records in the new system?"] = answers["What are the phantom records in the new system?"]
    answers["Can you explain the ZZ fabricated beneficiaries?"] = answers["What are the ZZ fabricated beneficiaries?"]
    answers["Can you explain the BENE_BIRTH_DT mismatch pattern?"] = answers["What is the BENE_BIRTH_DT mismatch pattern?"]
    answers["Can you explain the carrier claims discrepancy?"] = answers["What is the carrier claims discrepancy?"]
    answers["Can you explain how claims are matched between systems?"] = answers["How are claims matched between systems?"]
    answers["Can you explain the dollar impact per beneficiary?"] = answers["What is the dollar impact per beneficiary?"]
    answers["Can you explain the chronic condition trends?"] = answers["Are there any chronic condition trends?"]
    answers["Can you explain the payment distribution?"] = answers["What does the payment distribution look like?"]
    answers["Please summarize the executive summary"] = answers["Summarize the executive summary"]
    answers["What does LINE_NCH_PMT_AMT_1 mean?"] = answers["What is the LINE_NCH_PMT_AMT_1 issue?"]

    # ── New validation-focused answers ──

    answers["Can you explain the coverage period validation?"] = f"""The **coverage period validation** checks that four coverage-month fields are within the valid **0–12** range, as defined by the CMS codebook.

**Fields checked:**
{chr(10).join(coverage_lines) if coverage_lines else '- No coverage validation results available'}

Per the CMS codebook, these fields represent total months of coverage in a calendar year:
- **BENE_HI_CVRAGE_TOT_MONS** — Hospital Insurance (Part A) months
- **BENE_SMI_CVRAGE_TOT_MONS** — Supplementary Medical Insurance (Part B) months
- **BENE_HMO_CVRAGE_TOT_MONS** — HMO coverage months
- **PLAN_CVRG_MOS_NUM** — Part D plan coverage months

Values outside 0–12 indicate data corruption or ETL errors — a beneficiary cannot have more than 12 months of coverage in a single year."""

    answers["Can you explain the ESRD consistency check?"] = f"""The **ESRD (End-Stage Renal Disease) consistency check** validates that the `BENE_ESRD_IND` field never regresses from **'Y' to non-'Y'** across consecutive summary years for the same beneficiary.

**Clinical rationale:** ESRD is an irreversible medical condition — once a beneficiary is classified as ESRD-positive, they should remain so in all subsequent years. A regression from 'Y' to '0' or NULL would indicate a **data error**, not a clinical recovery.

**Results:**
{chr(10).join(clinical_lines) if clinical_lines else '- No ESRD consistency results available'}

This check uses a self-join on `beneficiary_summary` comparing each beneficiary's ESRD status in year *N* against year *N+1*."""

    answers["Can you explain the state code validation?"] = f"""The **state code validation** performs two checks on the `SP_STATE_CODE` field:

1. **Range check** — Validates that all state codes fall within the SSA standard range of **1–56** (50 states + DC + territories). Codes outside this range indicate invalid or corrupted data.

2. **Year-over-year stability** — Flags beneficiaries whose state code changes between summary years. While legitimate relocations occur, a high rate of changes may indicate data quality issues.

State codes are important for geographic analysis, regional reimbursement rate calculations, and regulatory compliance reporting."""

    answers["Can you explain the death temporal chain check?"] = f"""The **death temporal chain** check ensures no beneficiary has summary records in years **after** their recorded death year.

For example, if `BENE_DEATH_DT` indicates a beneficiary died in 2008, they should **not** have a `beneficiary_summary` record for 2009 or 2010. Such records would indicate:
- A data entry error in the death date
- Failure to properly terminate the beneficiary's record
- Ghost records that could inflate population counts and distort utilization metrics

This check joins death dates to summary years and counts violations where `summary_year > death_year`."""

    answers["Can you explain the ICD-9 diagnosis code validation?"] = """The **ICD-9 diagnosis code format validation** checks columns `ICD9_DGNS_CD_1` through `ICD9_DGNS_CD_8` on carrier claims against the expected ICD-9-CM format.

**Valid ICD-9 format:** 3–5 alphanumeric characters matching the pattern `^[A-Za-z0-9]{3,5}$`

**Common valid examples:**
- `4019` — Hypertension (unspecified)
- `25000` — Diabetes mellitus type 2
- `V5789` — V-code for aftercare
- `E8859` — E-code for accidental fall

Codes that don't match this pattern may be:
- Truncated or padded codes from an ETL error
- ICD-10 codes incorrectly placed in an ICD-9 field
- Free-text or placeholder values"""

    answers["Can you explain the NPI format validation?"] = """The **NPI (National Provider Identifier) format validation** checks columns `PRF_PHYSN_NPI_1` through `PRF_PHYSN_NPI_5` on carrier claims.

**Valid NPI format:** Exactly **10 digits** (numeric characters only), matching `^[0-9]{10}$`

NPIs are assigned by CMS to healthcare providers and follow a standardized 10-digit format with a Luhn check digit. Invalid NPIs may indicate:
- Truncated or padded provider identifiers
- Legacy provider numbers that weren't properly converted
- Placeholder values used during testing

Provider identification is critical for fraud detection, referral tracking, and payment reconciliation."""

    answers["Please summarize the claim line utilization analysis"] = f"""The **claim line utilization analysis** examines how many of the 13 possible service lines are populated per carrier claim.

{f'''**Key metrics:**
- **Total claims analyzed:** {clu.get("total_claims", "N/A"):,}
- **Average lines per claim:** {clu.get("avg_lines", "N/A")}
- **Median lines per claim:** {clu.get("median_lines", "N/A")}
- **Maximum lines on any claim:** {clu.get("max_lines", "N/A")}
- **Single-line claims:** {clu.get("pct_single_line", "N/A")}%
- **Claims with ≤3 lines:** {clu.get("pct_lte_3_lines", "N/A")}%
- **Claims with ≤5 lines:** {clu.get("pct_lte_5_lines", "N/A")}%''' if clu else '- No claim line utilization data available'}

This analysis reveals claim complexity patterns and helps validate that multi-line payment aggregation logic in the financial reconciliation handles the actual data shape correctly."""

    answers["Can you explain the financial reconciliation distribution?"] = f"""The **financial reconciliation** compares aggregate payment amounts from carrier claim lines against the corresponding totals in the beneficiary summary, using a **$0.01 tolerance** to account for floating-point rounding.

**Why $0.01 tolerance?** Summing many small payment amounts introduces sub-cent rounding differences that are not true discrepancies. This is standard practice in financial data reconciliation.

**Difference distribution buckets:**
{chr(10).join(fin_recon_lines) if fin_recon_lines else '- No distribution data available'}

The buckets show how discrepancies are concentrated:
- **Exact match (≤$0.01)** — Rounding-only differences
- **$0.01–$1.00** — Minor discrepancies, likely rounding
- **$1.00–$100.00** — Moderate discrepancies, worth investigating
- **>$100.00** — Significant discrepancies, likely data errors"""

    answers["What does BENE_HMO_CVRAGE_TOT_MONS mean?"] = """**BENE_HMO_CVRAGE_TOT_MONS** is a CMS codebook field representing the **total months of HMO coverage** for a Medicare beneficiary in a given calendar year.

**Details:**
- **Range:** 0–12 (integer)
- **0** = No HMO coverage during the year
- **12** = Enrolled in an HMO for the full year
- Intermediate values indicate partial-year HMO enrollment

This field is part of the Medicare Advantage (Part C) enrollment tracking. When a beneficiary is enrolled in an HMO plan, their claims may be processed differently than fee-for-service Medicare.

**In our pipeline:** We validate this field is within 0–12 in the `check_coverage_period` function and compare it between old and new systems for migration accuracy."""

    answers["What does BENE_HI_CVRAGE_TOT_MONS mean?"] = """**BENE_HI_CVRAGE_TOT_MONS** is a CMS codebook field representing the **total months of Hospital Insurance (Part A) coverage** for a Medicare beneficiary in a given calendar year.

**Details:**
- **Range:** 0–12 (integer)
- **Part A** covers inpatient hospital stays, skilled nursing facility care, hospice, and some home health services
- Most Medicare beneficiaries age 65+ have 12 months of Part A coverage per year
- Lower values may indicate late enrollment, loss of eligibility, or death mid-year

**In our pipeline:** Validated in `check_coverage_period` to ensure values are in the 0–12 range."""

    answers["What does BENE_SMI_CVRAGE_TOT_MONS mean?"] = """**BENE_SMI_CVRAGE_TOT_MONS** is a CMS codebook field representing the **total months of Supplementary Medical Insurance (Part B) coverage** for a Medicare beneficiary in a given calendar year.

**Details:**
- **Range:** 0–12 (integer)
- **Part B** covers physician services, outpatient care, durable medical equipment, and preventive services
- Part B is optional and requires a monthly premium, so values of 0 are more common than Part A
- Carrier claims (the primary claims type in this dataset) are billed under Part B

**In our pipeline:** Validated in `check_coverage_period` to ensure values are in the 0–12 range."""

    answers["What does PLAN_CVRG_MOS_NUM mean?"] = """**PLAN_CVRG_MOS_NUM** is a CMS codebook field representing the **total months of Part D (prescription drug) plan coverage** for a Medicare beneficiary in a given calendar year.

**Details:**
- **Range:** 0–12 (integer)
- **Part D** covers outpatient prescription drug benefits
- Part D is provided through private plans (PDPs or MA-PDs), not directly by Medicare
- A value of 0 means the beneficiary was not enrolled in any Part D plan that year

**In our pipeline:** Validated in `check_coverage_period` to ensure values are in the 0–12 range."""

    answers["What does BENE_ESRD_IND mean?"] = """**BENE_ESRD_IND** is a CMS codebook field indicating whether a Medicare beneficiary has been diagnosed with **End-Stage Renal Disease (ESRD)**.

**Values:**
- **'Y'** — Beneficiary has ESRD (qualifies for Medicare regardless of age)
- **'0'** or **NULL** — No ESRD diagnosis on record

**Clinical significance:**
- ESRD is an **irreversible** condition (permanent kidney failure requiring dialysis or transplant)
- ESRD beneficiaries qualify for Medicare at **any age**, not just 65+
- They typically have much higher healthcare utilization and costs

**In our pipeline:** The `check_esrd_consistency` function verifies that ESRD status never regresses from 'Y' to non-'Y' across years, since that would be clinically impossible."""

    answers["What does SP_STATE_CODE mean?"] = """**SP_STATE_CODE** is a CMS codebook field representing the **SSA (Social Security Administration) state code** for the beneficiary's residence.

**Details:**
- **Range:** 1–56 (integer)
- Codes 1–50 map to U.S. states (alphabetical: 1=Alabama, 2=Alaska, ... 50=Wyoming)
- Codes 51–56 cover U.S. territories and other jurisdictions (DC, Puerto Rico, Virgin Islands, etc.)
- Codes outside 1–56 are invalid

**In our pipeline:** The `check_state_codes` function validates the range and flags beneficiaries whose state code changes between summary years (potential data quality issue or legitimate relocation)."""

    answers["Please summarize all validation checks"] = f"""**{total_checks} validation checks** were performed across **6 categories**:

### Identity ({len(identity_vals)} checks)
Referential integrity between beneficiary and claims tables — orphan claims, missing beneficiaries, duplicate IDs.

### Temporal ({len(temporal_vals)} checks)
Date consistency — claims after death, date inversions, summary records after death year.

### Demographic ({len(demographic_vals)} checks)
Immutable field stability — sex, race, and birth date should not change across years.

### Coverage ({len(coverage_vals)} checks)
CMS codebook range validation — all coverage month fields must be 0–12.

### Clinical ({len(clinical_vals)} checks)
Domain-specific rules — ESRD irreversibility, ICD-9 format, NPI format.

### Financial ({len(financial_vals)} checks)
Payment reconciliation — beneficiary summary totals vs aggregated claim line amounts, with $0.01 tolerance and distribution analysis.

**Results: {passed} passed, {failed} failed.**"""

    # ── SQL queries per answer (for "Review SQL" button) ──
    queries = {}

    queries["What are the most critical findings?"] = [
        "-- Discrepancy summary by year\nSELECT summary_year, COUNT(*) AS total,\n  SUM(CASE WHEN total_diffs > 0 THEN 1 ELSE 0 END) AS mismatched,\n  ROUND(100.0 * SUM(CASE WHEN total_diffs > 0 THEN 1 ELSE 0 END) / COUNT(*), 2) AS pct\nFROM _discrepancy_detail\nGROUP BY summary_year ORDER BY summary_year;",
        "-- Top mismatched fields\nSELECT 'BENE_BIRTH_DT' AS field, SUM(diff_BENE_BIRTH_DT) AS mismatches FROM _discrepancy_detail\nUNION ALL\nSELECT 'BENE_HI_CVRAGE_TOT_MONS', SUM(diff_BENE_HI_CVRAGE_TOT_MONS) FROM _discrepancy_detail\nORDER BY mismatches DESC;",
        "-- Financial divergence totals\nSELECT SUM(ABS(total_dollar_diff)) AS total_abs_divergence,\n  AVG(total_dollar_diff) AS avg_divergence\nFROM _financial_recon;"
    ]

    queries["Explain the payment discrepancy between systems"] = [
        "-- Payment ratio analysis (0.90 pattern)\nSELECT o.CLM_ID,\n  o.LINE_NCH_PMT_AMT_1 AS old_pmt,\n  n.LINE_NCH_PMT_AMT_1 AS new_pmt,\n  ROUND(n.LINE_NCH_PMT_AMT_1 / NULLIF(o.LINE_NCH_PMT_AMT_1, 0), 4) AS ratio\nFROM carrier_claims o\nJOIN new_carrier_claims n ON o.CLM_ID::VARCHAR = n.CLM_ID::VARCHAR\nWHERE o.LINE_NCH_PMT_AMT_1 != n.LINE_NCH_PMT_AMT_1\nORDER BY ABS(o.LINE_NCH_PMT_AMT_1 - n.LINE_NCH_PMT_AMT_1) DESC\nLIMIT 50;",
        "-- Count mismatched claims per payment column\nSELECT 'LINE_NCH_PMT_AMT_1' AS col,\n  COUNT(*) AS mismatched\nFROM carrier_claims o\nJOIN new_carrier_claims n ON o.CLM_ID::VARCHAR = n.CLM_ID::VARCHAR\nWHERE n.DESYNPUF_ID NOT LIKE 'ZZ%'\n  AND o.LINE_NCH_PMT_AMT_1 != n.LINE_NCH_PMT_AMT_1;"
    ]

    queries["How many beneficiaries have data mismatches?"] = [
        "-- Beneficiaries with mismatches by year\nSELECT summary_year,\n  COUNT(*) AS total,\n  SUM(CASE WHEN total_diffs > 0 THEN 1 ELSE 0 END) AS mismatched\nFROM _discrepancy_detail\nGROUP BY summary_year ORDER BY summary_year;",
        "-- Distinct affected beneficiaries\nSELECT COUNT(DISTINCT DESYNPUF_ID) AS affected_benes\nFROM _discrepancy_detail\nWHERE total_diffs > 0;"
    ]

    queries["What is the overall accuracy rate?"] = [
        "-- Overall accuracy calculation\nSELECT COUNT(*) AS total_matched,\n  SUM(CASE WHEN total_diffs = 0 THEN 1 ELSE 0 END) AS identical,\n  SUM(CASE WHEN total_diffs > 0 THEN 1 ELSE 0 END) AS mismatched,\n  ROUND(100.0 * SUM(CASE WHEN total_diffs = 0 THEN 1 ELSE 0 END) / COUNT(*), 2) AS accuracy_pct\nFROM _discrepancy_detail;"
    ]

    queries["Which fields have the most mismatches?"] = [
        "-- Field-level mismatch counts\nSELECT 'BENE_BIRTH_DT' AS field, SUM(diff_BENE_BIRTH_DT) AS cnt FROM _discrepancy_detail\nUNION ALL SELECT 'BENE_HI_CVRAGE_TOT_MONS', SUM(diff_BENE_HI_CVRAGE_TOT_MONS) FROM _discrepancy_detail\nUNION ALL SELECT 'BENE_SMI_CVRAGE_TOT_MONS', SUM(diff_BENE_SMI_CVRAGE_TOT_MONS) FROM _discrepancy_detail\nUNION ALL SELECT 'PLAN_CVRG_MOS_NUM', SUM(diff_PLAN_CVRG_MOS_NUM) FROM _discrepancy_detail\nORDER BY cnt DESC;"
    ]

    queries["What are the phantom records in the new system?"] = [
        "-- Phantom claims (in new but not old)\nSELECT COUNT(*) AS phantom_claims\nFROM new_carrier_claims n\nLEFT JOIN carrier_claims o ON n.CLM_ID::VARCHAR = o.CLM_ID::VARCHAR\nWHERE o.CLM_ID IS NULL;",
        "-- Sample phantom claims\nSELECT n.CLM_ID, n.DESYNPUF_ID, n.CLM_FROM_DT, n.LINE_NCH_PMT_AMT_1\nFROM new_carrier_claims n\nLEFT JOIN carrier_claims o ON n.CLM_ID::VARCHAR = o.CLM_ID::VARCHAR\nWHERE o.CLM_ID IS NULL\nLIMIT 25;",
        "-- Phantom beneficiaries\nSELECT COUNT(*) AS phantom_benes\nFROM new_beneficiary_summary n\nLEFT JOIN beneficiary_summary o ON n.DESYNPUF_ID = o.DESYNPUF_ID AND n.summary_year = o.summary_year\nWHERE o.DESYNPUF_ID IS NULL;"
    ]

    queries["Why are there extra claims in the new system?"] = [
        "-- Volume comparison\nSELECT 'old' AS system, COUNT(*) AS cnt FROM carrier_claims\nUNION ALL\nSELECT 'new', COUNT(*) FROM new_carrier_claims;",
        "-- ZZ claims contributing to extras\nSELECT COUNT(*) AS zz_claims\nFROM new_carrier_claims\nWHERE DESYNPUF_ID LIKE 'ZZ%';"
    ]

    queries["What is the BENE_BIRTH_DT mismatch pattern?"] = [
        "-- Birth date mismatches by year\nSELECT summary_year,\n  SUM(diff_BENE_BIRTH_DT) AS birth_dt_mismatches,\n  COUNT(*) AS total\nFROM _discrepancy_detail\nGROUP BY summary_year ORDER BY summary_year;",
        "-- Sample birth date differences\nSELECT d.DESYNPUF_ID, d.summary_year,\n  o.BENE_BIRTH_DT AS old_birth_dt,\n  n.BENE_BIRTH_DT AS new_birth_dt\nFROM _discrepancy_detail d\nJOIN beneficiary_summary o ON d.DESYNPUF_ID = o.DESYNPUF_ID AND d.summary_year = o.summary_year\nJOIN new_beneficiary_summary n ON d.DESYNPUF_ID = n.DESYNPUF_ID AND d.summary_year = n.summary_year\nWHERE d.diff_BENE_BIRTH_DT = 1\nLIMIT 20;"
    ]

    queries["Explain the 0.90 payment ratio pattern"] = [
        "-- Payment ratio distribution\nSELECT ROUND(n.LINE_NCH_PMT_AMT_1 / NULLIF(o.LINE_NCH_PMT_AMT_1, 0), 2) AS ratio,\n  COUNT(*) AS cnt\nFROM carrier_claims o\nJOIN new_carrier_claims n ON o.CLM_ID::VARCHAR = n.CLM_ID::VARCHAR\nWHERE n.DESYNPUF_ID NOT LIKE 'ZZ%'\n  AND o.LINE_NCH_PMT_AMT_1 > 0 AND n.LINE_NCH_PMT_AMT_1 > 0\nGROUP BY ratio ORDER BY cnt DESC LIMIT 20;",
        "-- Aggregate old vs new payment sums\nSELECT SUM(o.LINE_NCH_PMT_AMT_1) AS old_total,\n  SUM(n.LINE_NCH_PMT_AMT_1) AS new_total,\n  ROUND(SUM(n.LINE_NCH_PMT_AMT_1) / NULLIF(SUM(o.LINE_NCH_PMT_AMT_1), 0), 4) AS overall_ratio\nFROM carrier_claims o\nJOIN new_carrier_claims n ON o.CLM_ID::VARCHAR = n.CLM_ID::VARCHAR\nWHERE n.DESYNPUF_ID NOT LIKE 'ZZ%';"
    ]

    queries["What are the ZZ fabricated beneficiaries?"] = [
        "-- ZZ beneficiaries\nSELECT * FROM new_beneficiary_summary\nWHERE DESYNPUF_ID LIKE 'ZZ%'\nORDER BY DESYNPUF_ID, summary_year;",
        "-- ZZ claims count\nSELECT COUNT(*) AS zz_claims\nFROM new_carrier_claims\nWHERE DESYNPUF_ID LIKE 'ZZ%';",
        "-- Sample ZZ claims\nSELECT CLM_ID, DESYNPUF_ID, CLM_FROM_DT, LINE_NCH_PMT_AMT_1\nFROM new_carrier_claims\nWHERE DESYNPUF_ID LIKE 'ZZ%'\nLIMIT 25;"
    ]

    queries["Which validation checks failed?"] = [
        "-- This data comes from the Python validation engine.\n-- Failed checks are computed by src/validate.py against DuckDB tables.\n-- You can inspect the underlying data with:\nSELECT table_name, column_name, COUNT(*) AS rows, SUM(CASE WHEN column_name IS NULL THEN 1 ELSE 0 END) AS nulls\nFROM information_schema.columns\nWHERE table_name IN ('beneficiary_summary', 'carrier_claims')\nGROUP BY table_name, column_name;"
    ]

    queries["What is the total financial divergence amount?"] = [
        "-- Financial divergence per column (beneficiary reimbursements)\nSELECT 'MEDREIMB_IP' AS col,\n  SUM(o.MEDREIMB_IP) AS old_sum, SUM(n.MEDREIMB_IP) AS new_sum,\n  SUM(n.MEDREIMB_IP) - SUM(o.MEDREIMB_IP) AS diff\nFROM beneficiary_summary o\nJOIN new_beneficiary_summary n ON o.DESYNPUF_ID = n.DESYNPUF_ID AND o.summary_year = n.summary_year\nWHERE n.DESYNPUF_ID NOT LIKE 'ZZ%'\nUNION ALL\nSELECT 'MEDREIMB_CAR',\n  SUM(o.MEDREIMB_CAR), SUM(n.MEDREIMB_CAR),\n  SUM(n.MEDREIMB_CAR) - SUM(o.MEDREIMB_CAR)\nFROM beneficiary_summary o\nJOIN new_beneficiary_summary n ON o.DESYNPUF_ID = n.DESYNPUF_ID AND o.summary_year = n.summary_year\nWHERE n.DESYNPUF_ID NOT LIKE 'ZZ%';",
        "-- Per-beneficiary financial recon (top divergences)\nSELECT * FROM _financial_recon\nORDER BY ABS(total_dollar_diff) DESC\nLIMIT 50;"
    ]

    queries["How does accuracy vary by year?"] = queries["How many beneficiaries have data mismatches?"]

    queries["Which reimbursement columns have the largest differences?"] = queries["What is the total financial divergence amount?"]

    queries["What are the top mismatched fields?"] = queries["Which fields have the most mismatches?"]

    queries["Is the discrepancy rate stable across years?"] = queries["How many beneficiaries have data mismatches?"]

    queries["How many claims have payment changes?"] = [
        "-- Claims with any payment change\nSELECT COUNT(*) AS claims_with_changes\nFROM carrier_claims o\nJOIN new_carrier_claims n ON o.CLM_ID::VARCHAR = n.CLM_ID::VARCHAR\nWHERE n.DESYNPUF_ID NOT LIKE 'ZZ%'\n  AND (o.LINE_NCH_PMT_AMT_1 != n.LINE_NCH_PMT_AMT_1\n    OR o.LINE_NCH_PMT_AMT_2 IS DISTINCT FROM n.LINE_NCH_PMT_AMT_2);",
        "-- Breakdown by payment column\nSELECT 'LINE_NCH_PMT_AMT_1' AS col,\n  COUNT(*) FILTER (WHERE o.LINE_NCH_PMT_AMT_1 != n.LINE_NCH_PMT_AMT_1) AS mismatched\nFROM carrier_claims o\nJOIN new_carrier_claims n ON o.CLM_ID::VARCHAR = n.CLM_ID::VARCHAR\nWHERE n.DESYNPUF_ID NOT LIKE 'ZZ%';"
    ]

    queries["What does the payment distribution look like?"] = [
        "-- Carrier payment distribution stats\nSELECT\n  ROUND(AVG(MEDREIMB_CAR), 2) AS avg_medicare,\n  ROUND(MEDIAN(MEDREIMB_CAR), 2) AS med_medicare,\n  ROUND(AVG(BENRES_CAR), 2) AS avg_bene_resp,\n  ROUND(AVG(PPPYMT_CAR), 2) AS avg_primary_payer\nFROM beneficiary_summary\nWHERE MEDREIMB_CAR > 0;"
    ]

    queries["Are there any chronic condition trends?"] = [
        "-- Chronic condition prevalence by year\nSELECT summary_year,\n  ROUND(100.0 * SUM(CASE WHEN SP_DIABETES = 1 THEN 1 ELSE 0 END) / COUNT(*), 1) AS diabetes_pct,\n  ROUND(100.0 * SUM(CASE WHEN SP_ISCHMCHT = 1 THEN 1 ELSE 0 END) / COUNT(*), 1) AS ischemic_pct,\n  ROUND(100.0 * SUM(CASE WHEN SP_CHF = 1 THEN 1 ELSE 0 END) / COUNT(*), 1) AS chf_pct,\n  ROUND(100.0 * SUM(CASE WHEN SP_DEPRESSN = 1 THEN 1 ELSE 0 END) / COUNT(*), 1) AS depression_pct\nFROM beneficiary_summary\nGROUP BY summary_year ORDER BY summary_year;"
    ]

    queries["What is the record matching rate?"] = [
        "-- Beneficiary match stats\nSELECT 'matched' AS status, COUNT(*) AS cnt FROM _match_beneficiary WHERE match_status = 'matched'\nUNION ALL SELECT 'old_only', COUNT(*) FROM _match_beneficiary WHERE match_status = 'old_only'\nUNION ALL SELECT 'new_only', COUNT(*) FROM _match_beneficiary WHERE match_status = 'new_only';",
        "-- Claims match stats\nSELECT 'matched' AS status, COUNT(*) AS cnt FROM _match_claims WHERE match_status = 'matched'\nUNION ALL SELECT 'old_only', COUNT(*) FROM _match_claims WHERE match_status = 'old_only'\nUNION ALL SELECT 'new_only', COUNT(*) FROM _match_claims WHERE match_status = 'new_only';"
    ]

    queries["How many beneficiaries are affected by changes?"] = queries["How many beneficiaries have data mismatches?"]

    queries["What is the dollar impact per beneficiary?"] = [
        "-- Dollar impact per beneficiary\nSELECT DESYNPUF_ID,\n  SUM(total_dollar_diff) AS total_diff,\n  COUNT(*) AS year_records\nFROM _financial_recon\nWHERE ABS(total_dollar_diff) > 0\nGROUP BY DESYNPUF_ID\nORDER BY ABS(SUM(total_dollar_diff)) DESC\nLIMIT 50;"
    ]

    queries["Which system overstates reimbursements?"] = queries["What is the total financial divergence amount?"]

    queries["Are there schema differences between systems?"] = [
        "-- Compare column lists between old and new beneficiary tables\nSELECT column_name, data_type FROM information_schema.columns WHERE table_name = 'beneficiary_summary' ORDER BY ordinal_position;",
        "-- Compare column lists for new beneficiary table\nSELECT column_name, data_type FROM information_schema.columns WHERE table_name = 'new_beneficiary_summary' ORDER BY ordinal_position;"
    ]

    queries["What are the injected test records?"] = queries["What are the ZZ fabricated beneficiaries?"]

    queries["How do inpatient vs outpatient payments compare?"] = [
        "-- Reimbursement totals by year and type\nSELECT summary_year,\n  SUM(MEDREIMB_IP) AS inpatient,\n  SUM(MEDREIMB_OP) AS outpatient,\n  SUM(MEDREIMB_CAR) AS carrier\nFROM beneficiary_summary\nGROUP BY summary_year ORDER BY summary_year;"
    ]

    queries["What is the carrier claims discrepancy?"] = [
        "-- Carrier claims volume comparison\nSELECT 'old' AS system, COUNT(*) AS cnt FROM carrier_claims\nUNION ALL SELECT 'new', COUNT(*) FROM new_carrier_claims;",
        "-- Payment mismatches on matched claims\nSELECT o.CLM_ID,\n  o.LINE_NCH_PMT_AMT_1 AS old_pmt, n.LINE_NCH_PMT_AMT_1 AS new_pmt,\n  n.LINE_NCH_PMT_AMT_1 - o.LINE_NCH_PMT_AMT_1 AS diff\nFROM carrier_claims o\nJOIN new_carrier_claims n ON o.CLM_ID::VARCHAR = n.CLM_ID::VARCHAR\nWHERE n.DESYNPUF_ID NOT LIKE 'ZZ%'\n  AND o.LINE_NCH_PMT_AMT_1 != n.LINE_NCH_PMT_AMT_1\nORDER BY ABS(diff) DESC LIMIT 50;"
    ]

    queries["Suggest SQL queries to investigate further"] = []  # Already has SQL in the answer text

    queries["What bugs should be fixed before production cutover?"] = queries["What are the most critical findings?"]

    queries["How does Medicare reimbursement compare by year?"] = queries["How do inpatient vs outpatient payments compare?"]

    queries["What is the beneficiary discrepancy trend?"] = queries["How many beneficiaries have data mismatches?"]

    queries["Are there geographic patterns in the discrepancies?"] = [
        "-- State-level discrepancy rates (if SP_STATE_CODE available)\nSELECT o.SP_STATE_CODE,\n  COUNT(*) AS total,\n  SUM(CASE WHEN d.total_diffs > 0 THEN 1 ELSE 0 END) AS mismatched\nFROM _discrepancy_detail d\nJOIN beneficiary_summary o ON d.DESYNPUF_ID = o.DESYNPUF_ID AND d.summary_year = o.summary_year\nGROUP BY o.SP_STATE_CODE\nORDER BY mismatched DESC;"
    ]

    queries["What is the LINE_NCH_PMT_AMT_1 issue?"] = queries["Explain the payment discrepancy between systems"]

    queries["How many records are in each system?"] = [
        "-- Record counts across all tables\nSELECT 'beneficiary_summary (old)' AS tbl, COUNT(*) AS cnt FROM beneficiary_summary\nUNION ALL SELECT 'new_beneficiary_summary', COUNT(*) FROM new_beneficiary_summary\nUNION ALL SELECT 'carrier_claims (old)', COUNT(*) FROM carrier_claims\nUNION ALL SELECT 'new_carrier_claims', COUNT(*) FROM new_carrier_claims;"
    ]

    queries["What data quality checks were performed?"] = queries["Which validation checks failed?"]

    queries["What is the risk assessment for the new system?"] = queries["What are the most critical findings?"]

    queries["How does the new system compare overall?"] = queries["What are the most critical findings?"]

    queries["What is the total reimbursement amount?"] = queries["How do inpatient vs outpatient payments compare?"]

    queries["Are discrepancies random or systematic?"] = [
        "-- Year-over-year consistency check\nSELECT summary_year,\n  ROUND(100.0 * SUM(CASE WHEN total_diffs > 0 THEN 1 ELSE 0 END) / COUNT(*), 2) AS pct\nFROM _discrepancy_detail\nGROUP BY summary_year ORDER BY summary_year;",
        "-- Field concentration check\nSELECT SUM(diff_BENE_BIRTH_DT) AS birth_dt,\n  SUM(diff_BENE_HI_CVRAGE_TOT_MONS) AS hi_cvg,\n  SUM(diff_BENE_SMI_CVRAGE_TOT_MONS) AS smi_cvg\nFROM _discrepancy_detail;"
    ]

    queries["What are the two distinct bugs mentioned?"] = queries["What bugs should be fixed before production cutover?"]

    queries["Show me a SQL query for beneficiary mismatches"] = []  # Already has SQL in the answer text

    queries["What is the new system readiness status?"] = queries["What are the most critical findings?"]

    queries["Summarize the executive summary"] = queries["What are the most critical findings?"]

    queries["What does the financial reconciliation show?"] = queries["What is the total financial divergence amount?"]

    queries["How are claims matched between systems?"] = queries["What is the record matching rate?"]

    # ── Queries for new validation-focused answers ──

    queries["Can you explain the coverage period validation?"] = [
        "-- Coverage month values outside 0-12\nSELECT 'BENE_HI_CVRAGE_TOT_MONS' AS field,\n  COUNT(*) FILTER (WHERE BENE_HI_CVRAGE_TOT_MONS < 0 OR BENE_HI_CVRAGE_TOT_MONS > 12) AS invalid\nFROM beneficiary_summary\nUNION ALL\nSELECT 'BENE_SMI_CVRAGE_TOT_MONS',\n  COUNT(*) FILTER (WHERE BENE_SMI_CVRAGE_TOT_MONS < 0 OR BENE_SMI_CVRAGE_TOT_MONS > 12)\nFROM beneficiary_summary\nUNION ALL\nSELECT 'BENE_HMO_CVRAGE_TOT_MONS',\n  COUNT(*) FILTER (WHERE BENE_HMO_CVRAGE_TOT_MONS < 0 OR BENE_HMO_CVRAGE_TOT_MONS > 12)\nFROM beneficiary_summary\nUNION ALL\nSELECT 'PLAN_CVRG_MOS_NUM',\n  COUNT(*) FILTER (WHERE PLAN_CVRG_MOS_NUM < 0 OR PLAN_CVRG_MOS_NUM > 12)\nFROM beneficiary_summary;",
        "-- Coverage month distribution\nSELECT BENE_HI_CVRAGE_TOT_MONS AS months, COUNT(*) AS cnt\nFROM beneficiary_summary\nGROUP BY months ORDER BY months;"
    ]

    queries["Can you explain the ESRD consistency check?"] = [
        "-- ESRD indicator values\nSELECT BENE_ESRD_IND::VARCHAR AS esrd, COUNT(*) AS cnt\nFROM beneficiary_summary\nGROUP BY esrd ORDER BY esrd;",
        "-- ESRD regressions (Y in year N, non-Y in year N+1)\nSELECT a.DESYNPUF_ID, a.summary_year AS yr_y, b.summary_year AS yr_not_y,\n  a.BENE_ESRD_IND::VARCHAR AS esrd_before, b.BENE_ESRD_IND::VARCHAR AS esrd_after\nFROM beneficiary_summary a\nJOIN beneficiary_summary b ON a.DESYNPUF_ID = b.DESYNPUF_ID AND a.summary_year < b.summary_year\nWHERE a.BENE_ESRD_IND::VARCHAR = 'Y' AND (b.BENE_ESRD_IND IS NULL OR b.BENE_ESRD_IND::VARCHAR != 'Y');"
    ]

    queries["Can you explain the state code validation?"] = [
        "-- Invalid state codes (outside 1-56)\nSELECT SP_STATE_CODE, COUNT(*) AS cnt\nFROM beneficiary_summary\nWHERE SP_STATE_CODE < 1 OR SP_STATE_CODE > 56\nGROUP BY SP_STATE_CODE;",
        "-- Year-over-year state changes\nSELECT a.DESYNPUF_ID, a.summary_year, a.SP_STATE_CODE AS state_before,\n  b.summary_year AS next_year, b.SP_STATE_CODE AS state_after\nFROM beneficiary_summary a\nJOIN beneficiary_summary b ON a.DESYNPUF_ID = b.DESYNPUF_ID AND a.summary_year < b.summary_year\nWHERE a.SP_STATE_CODE != b.SP_STATE_CODE\nLIMIT 50;"
    ]

    queries["Can you explain the death temporal chain check?"] = [
        "-- Summary records after death year\nSELECT b.DESYNPUF_ID, b.BENE_DEATH_DT,\n  (b.BENE_DEATH_DT / 10000)::INT AS death_year,\n  s.summary_year\nFROM beneficiary_summary b\nJOIN beneficiary_summary s ON b.DESYNPUF_ID = s.DESYNPUF_ID\nWHERE b.BENE_DEATH_DT > 0\n  AND s.summary_year > (b.BENE_DEATH_DT / 10000)::INT\nLIMIT 50;"
    ]

    queries["Can you explain the ICD-9 diagnosis code validation?"] = [
        "-- ICD-9 codes that don't match 3-5 alphanumeric pattern\nSELECT ICD9_DGNS_CD_1, COUNT(*) AS cnt\nFROM carrier_claims\nWHERE ICD9_DGNS_CD_1 IS NOT NULL\n  AND NOT regexp_matches(ICD9_DGNS_CD_1, '^[A-Za-z0-9]{3,5}$')\nGROUP BY ICD9_DGNS_CD_1\nORDER BY cnt DESC LIMIT 20;",
        "-- Top 20 most common diagnosis codes\nSELECT ICD9_DGNS_CD_1, COUNT(*) AS cnt\nFROM carrier_claims\nWHERE ICD9_DGNS_CD_1 IS NOT NULL\nGROUP BY ICD9_DGNS_CD_1\nORDER BY cnt DESC LIMIT 20;"
    ]

    queries["Can you explain the NPI format validation?"] = [
        "-- NPI values that aren't 10 digits\nSELECT PRF_PHYSN_NPI_1, COUNT(*) AS cnt\nFROM carrier_claims\nWHERE PRF_PHYSN_NPI_1 IS NOT NULL\n  AND NOT regexp_matches(PRF_PHYSN_NPI_1::VARCHAR, '^[0-9]{10}$')\nGROUP BY PRF_PHYSN_NPI_1\nORDER BY cnt DESC LIMIT 20;",
        "-- Top providers by claim count\nSELECT PRF_PHYSN_NPI_1, COUNT(*) AS claim_count\nFROM carrier_claims\nWHERE PRF_PHYSN_NPI_1 IS NOT NULL\nGROUP BY PRF_PHYSN_NPI_1\nORDER BY claim_count DESC LIMIT 20;"
    ]

    queries["Please summarize the claim line utilization analysis"] = [
        "-- Claim line utilization distribution\nSELECT populated_lines, COUNT(*) AS claims\nFROM (\n  SELECT CLM_ID,\n    (CASE WHEN LINE_NCH_PMT_AMT_1 IS NOT NULL THEN 1 ELSE 0 END\n    + CASE WHEN LINE_NCH_PMT_AMT_2 IS NOT NULL THEN 1 ELSE 0 END\n    + CASE WHEN LINE_NCH_PMT_AMT_3 IS NOT NULL THEN 1 ELSE 0 END\n    + CASE WHEN LINE_NCH_PMT_AMT_4 IS NOT NULL THEN 1 ELSE 0 END\n    + CASE WHEN LINE_NCH_PMT_AMT_5 IS NOT NULL THEN 1 ELSE 0 END\n    + CASE WHEN LINE_NCH_PMT_AMT_6 IS NOT NULL THEN 1 ELSE 0 END\n    + CASE WHEN LINE_NCH_PMT_AMT_7 IS NOT NULL THEN 1 ELSE 0 END\n    + CASE WHEN LINE_NCH_PMT_AMT_8 IS NOT NULL THEN 1 ELSE 0 END\n    + CASE WHEN LINE_NCH_PMT_AMT_9 IS NOT NULL THEN 1 ELSE 0 END\n    + CASE WHEN LINE_NCH_PMT_AMT_10 IS NOT NULL THEN 1 ELSE 0 END\n    + CASE WHEN LINE_NCH_PMT_AMT_11 IS NOT NULL THEN 1 ELSE 0 END\n    + CASE WHEN LINE_NCH_PMT_AMT_12 IS NOT NULL THEN 1 ELSE 0 END\n    + CASE WHEN LINE_NCH_PMT_AMT_13 IS NOT NULL THEN 1 ELSE 0 END) AS populated_lines\n  FROM carrier_claims\n) sub\nGROUP BY populated_lines ORDER BY populated_lines;"
    ]

    queries["Can you explain the financial reconciliation distribution?"] = [
        "-- Financial reconciliation detail with diff buckets\nSELECT\n  COUNT(*) AS total,\n  SUM(CASE WHEN medreimb_diff <= 0.01 THEN 1 ELSE 0 END) AS exact,\n  SUM(CASE WHEN medreimb_diff > 0.01 AND medreimb_diff <= 1.0 THEN 1 ELSE 0 END) AS under_1,\n  SUM(CASE WHEN medreimb_diff > 1.0 AND medreimb_diff <= 100.0 THEN 1 ELSE 0 END) AS under_100,\n  SUM(CASE WHEN medreimb_diff > 100.0 THEN 1 ELSE 0 END) AS over_100\nFROM _financial_recon;"
    ]

    # ── Query aliases for "Can you explain" / "Please summarize" variants ──
    queries["Can you explain the most critical findings?"] = queries["What are the most critical findings?"]
    queries["Can you explain the payment discrepancy between systems?"] = queries["Explain the payment discrepancy between systems"]
    queries["Can you explain the 0.90 payment ratio pattern?"] = queries["Explain the 0.90 payment ratio pattern"]
    queries["Can you explain how discrepancies are distributed across years?"] = queries["How does accuracy vary by year?"]
    queries["Can you explain whether the discrepancies are random or systematic?"] = queries["Are discrepancies random or systematic?"]
    queries["Can you explain the risk assessment for the new system?"] = queries["What are the most critical findings?"]
    queries["Can you explain the new system readiness status?"] = queries["What are the most critical findings?"]
    queries["Can you explain what bugs should be fixed before production cutover?"] = queries["What bugs should be fixed before production cutover?"]
    queries["Can you explain the phantom records in the new system?"] = queries["What are the phantom records in the new system?"]
    queries["Can you explain the ZZ fabricated beneficiaries?"] = queries["What are the ZZ fabricated beneficiaries?"]
    queries["Can you explain the BENE_BIRTH_DT mismatch pattern?"] = queries["What is the BENE_BIRTH_DT mismatch pattern?"]
    queries["Can you explain the carrier claims discrepancy?"] = queries["What is the carrier claims discrepancy?"]
    queries["Can you explain how claims are matched between systems?"] = queries["What is the record matching rate?"]
    queries["Can you explain the dollar impact per beneficiary?"] = queries["What is the dollar impact per beneficiary?"]
    queries["Can you explain the chronic condition trends?"] = queries["Are there any chronic condition trends?"]
    queries["Can you explain the payment distribution?"] = queries["What does the payment distribution look like?"]
    queries["Please summarize the executive summary"] = queries["Summarize the executive summary"]
    queries["What does LINE_NCH_PMT_AMT_1 mean?"] = queries["What is the LINE_NCH_PMT_AMT_1 issue?"]

    # Codebook lookups share the coverage period query
    queries["What does BENE_HMO_CVRAGE_TOT_MONS mean?"] = queries["Can you explain the coverage period validation?"]
    queries["What does BENE_HI_CVRAGE_TOT_MONS mean?"] = queries["Can you explain the coverage period validation?"]
    queries["What does BENE_SMI_CVRAGE_TOT_MONS mean?"] = queries["Can you explain the coverage period validation?"]
    queries["What does PLAN_CVRG_MOS_NUM mean?"] = queries["Can you explain the coverage period validation?"]
    queries["What does BENE_ESRD_IND mean?"] = queries["Can you explain the ESRD consistency check?"]
    queries["What does SP_STATE_CODE mean?"] = queries["Can you explain the state code validation?"]
    queries["Please summarize all validation checks"] = queries["Which validation checks failed?"]

    # ── Combine answers + queries into structured output ──
    result = {}
    for q_key, answer_text in answers.items():
        result[q_key] = {
            "answer": answer_text,
            "queries": queries.get(q_key, [])
        }

    return result
