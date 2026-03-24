# Documentation Index

A complete guide to all documentation in this project. Start with the document
that matches your role and goal.

---

## Quick Start by Role

| If you are... | Start here |
|---------------|-----------|
| **Reviewer / evaluator** | [REVIEWER_README.md](#reviewer_readmemd) → [FEEDBACK.md](#feedbackmd) |
| **Developer joining the team** | [README.md](#readmemd) → [PIPELINE.md](#pipelinemd) → [DATA_DICTIONARY.md](#data_dictionarymd) |
| **Interested in functional programming** | [FUNCTIONAL_ANALYSIS.md](#functional_analysismd) → [IMPERATIVE_VS_FUNCTIONAL.md](#imperative_vs_functionalmd) |
| **Checking requirements coverage** | [REQUIREMENTS_TRACEABILITY.md](#requirements_traceabilitymd) |
| **Understanding the architecture** | [SOLUTION.md](#solutionmd) → [PIPELINE.md](#pipelinemd) |

---

## Root-Level Documents

### README.md
- **Location:** [`/README.md`](../README.md)
- **Audience:** Everyone
- **Summary:** Project overview, prerequisites, quick start (Docker and local Python), data setup instructions, architecture diagram, and links to hosted report and documentation.
- **What to expect:** How to run the pipeline, what it does, where to find outputs.

### REVIEWER_README.md
- **Location:** [`/REVIEWER_README.md`](../REVIEWER_README.md)
- **Audience:** Assessment evaluators
- **Summary:** A guided tour of the project — what to look at, in what order, and why it matters. Includes links to the hosted report, documentation hub, and downloadable bundles.
- **What to expect:** Step-by-step walkthrough with screenshots, data setup instructions, and pointers to key findings.

### FEEDBACK.md
- **Location:** [`/FEEDBACK.md`](../FEEDBACK.md)
- **Audience:** Assessment evaluators
- **Summary:** Time spent, approach rationale, and how the author's expertise fits the assessment. Covers key design decisions (DuckDB, 6-step pipeline, report design, Docker).
- **What to expect:** Honest accounting of hours, design philosophy, and self-assessment.

### ARCHIVE_README.md
- **Location:** [`/ARCHIVE_README.md`](../ARCHIVE_README.md)
- **Audience:** Anyone opening the ZIP bundle
- **Summary:** Quick-start table for the archive contents — links to hosted versions, local setup, and directory structure of the archive.
- **What to expect:** A map of what's in the ZIP and where to go first.

### PIPELINE_SUMMARY_AND_WEAKNESSES.md
- **Location:** [`/PIPELINE_SUMMARY_AND_WEAKNESSES.md`](../PIPELINE_SUMMARY_AND_WEAKNESSES.md)
- **Audience:** Developers, reviewers interested in the original (imperative) implementation
- **Summary:** Detailed walkthrough of the original 6-step imperative pipeline architecture, step-by-step implementation summary, and a catalog of 10 weaknesses ranked by severity (mutable shared state, scattered error handling, DB coupling, testability, etc.). Each weakness includes code examples and impact analysis.
- **What to expect:** The "before" baseline that motivated the functional refactor. Includes a summary table mapping each weakness to its functional solution.

---

## docs/ — Core Documentation

### SOLUTION.md
- **Location:** [`docs/SOLUTION.md`](SOLUTION.md)
- **Audience:** Architects, senior developers, reviewers
- **Summary:** Design rationale for every major decision — why DuckDB over SQLite/Postgres/Spark/Pandas, why a 6-step pipeline with gate logic, report design philosophy, and Docker strategy.
- **What to expect:** Detailed "why" behind each technology and architectural choice, with comparisons to alternatives.

### PIPELINE.md
- **Location:** [`docs/PIPELINE.md`](PIPELINE.md)
- **Audience:** Developers, data engineers
- **Summary:** Canonical reference for the pipeline — step-by-step breakdown (Receive, Schema Validate, Ingest & Profile, Match & Validate, Compare & Analyze, Report), data model, validation checks reference, comparison checks reference, and output artifacts.
- **What to expect:** The authoritative technical reference for understanding what each step does, what it reads, and what it produces.

### DATA_DICTIONARY.md
- **Location:** [`docs/DATA_DICTIONARY.md`](DATA_DICTIONARY.md)
- **Audience:** Data engineers, analysts, anyone working with the data
- **Summary:** Complete schema documentation for the CMS DE-SynPUF dataset — beneficiary summary table (all columns), carrier claims table (all columns), old vs new system schema comparison, derived/internal tables, and guidance for using other CMS samples.
- **What to expect:** Column-level definitions, data types, value ranges, and codebook references for every field the pipeline touches.

### REQUIREMENTS_TRACEABILITY.md
- **Location:** [`docs/REQUIREMENTS_TRACEABILITY.md`](REQUIREMENTS_TRACEABILITY.md)
- **Audience:** Reviewers, compliance
- **Summary:** Maps every requirement from the USDS Data Engineer Take-Home Assessment to the specific component that fulfills it. Each requirement is marked FULFILLED with a table showing which file/function satisfies it.
- **What to expect:** A formal traceability matrix — if a requirement exists, this doc shows where and how it's met.

---

## docs/functional_programming/ — Functional Programming Documentation

### FUNCTIONAL_ANALYSIS.md
- **Location:** [`docs/functional_programming/FUNCTIONAL_ANALYSIS.md`](functional_programming/FUNCTIONAL_ANALYSIS.md)
- **Audience:** Reviewers, FP practitioners
- **Summary:** Executive summary of the complete functional refactoring — before/after architecture, all FP patterns implemented (immutable state, railway-oriented error handling, interpreter pattern, property-based testing, pattern matching), Z-set algebra implementation and findings (including the beneficiary swap discovery), and test results.
- **What to expect:** The high-level "what we did and what we found" document. Start here for the functional programming story.

### FUNCTIONAL_CONCEPTS.md
- **Location:** [`docs/functional_programming/FUNCTIONAL_CONCEPTS.md`](functional_programming/FUNCTIONAL_CONCEPTS.md)
- **Audience:** FP practitioners, developers learning FP
- **Summary:** Comprehensive catalog of every functional programming concept used in the codebase — 16 core concepts (monads, functors, composition, higher-order functions, closures, immutability, ADTs, pattern matching, pure functions, interpreter pattern, lazy evaluation, memoisation, fold/reduce, conditional combinators, property-based testing, recursion), 4 design patterns (railway-oriented programming, functional core/imperative shell, smart constructors, newtype), and 6 future extensions (lenses, free monads, comonads, recursive Z-sets, catamorphisms, trampolining). Each concept includes exact file locations and code examples.
- **What to expect:** A teaching document — explains each FP concept, then shows precisely where it appears in the code.

### Z-SET_USAGE.md
- **Location:** [`docs/functional_programming/Z-SET_USAGE.md`](functional_programming/Z-SET_USAGE.md)
- **Audience:** Anyone wanting to understand Z-set algebra in practice
- **Summary:** A detailed walkthrough of one complete Z-set calculation from start to finish — from pure SQL generation to DuckDB execution to interpreting results. Traces real data through `diff_sql()`, `stats_sql()`, `field_diff_sql()`, and `execute_diff()` with actual SQL and query results.
- **What to expect:** A hands-on tutorial. Follow along to understand exactly how Z-set diffs work on real CMS data.

### IMPERATIVE_VS_FUNCTIONAL.md
- **Location:** [`docs/functional_programming/IMPERATIVE_VS_FUNCTIONAL.md`](functional_programming/IMPERATIVE_VS_FUNCTIONAL.md)
- **Audience:** Reviewers, architects, anyone evaluating the refactor
- **Summary:** Balanced side-by-side comparison of the imperative and functional approaches. For each of the 8 original weaknesses, shows the imperative code, the functional replacement, what improved, and what gaps remain. Includes an honest assessment of what the imperative approach does well (simplicity, learning curve, debugging), the real costs of the functional approach (library dependency, verbosity, abstraction overhead), quantitative metrics (tests, runtime, LOC), and guidance on when to use which.
- **What to expect:** An honest, non-dogmatic comparison. Both approaches have strengths; this doc shows the trade-offs clearly.

---

## docs/ — Interactive HTML Documentation

These are browser-based tools served from the documentation hub.

| File | What It Is |
|------|-----------|
| [`index.html`](index.html) | Documentation hub landing page with navigation to all tools |
| [`architecture.html`](architecture.html) | Interactive architecture diagrams |
| [`pipeline.html`](pipeline.html) | Pipeline documentation (HTML version of PIPELINE.md) |
| [`solution.html`](solution.html) | Solution architecture (HTML version of SOLUTION.md) |
| [`data_dictionary.html`](data_dictionary.html) | Data dictionary (HTML version of DATA_DICTIONARY.md) |
| [`requirements_traceability.html`](requirements_traceability.html) | Requirements traceability (HTML version) |
| [`reviewer_readme.html`](reviewer_readme.html) | Reviewer walkthrough (HTML version with screenshots) |
| [`feedback.html`](feedback.html) | Assessment feedback (HTML version) |
| [`schema_explorer.html`](schema_explorer.html) | Interactive schema browser — explore table columns and types |
| [`sql_explorer.html`](sql_explorer.html) | Interactive SQL query tool — run queries against pipeline data |
| [`parquet_viewer.html`](parquet_viewer.html) | In-browser Parquet file viewer and query engine |

---

## Document Relationships

```
README.md (start here)
├── REVIEWER_README.md (guided tour for evaluators)
├── FEEDBACK.md (time, approach, self-assessment)
├── ARCHIVE_README.md (ZIP bundle guide)
│
├── docs/SOLUTION.md (why we built it this way)
├── docs/PIPELINE.md (what each step does)
├── docs/DATA_DICTIONARY.md (what the data looks like)
├── docs/REQUIREMENTS_TRACEABILITY.md (proof of coverage)
│
├── PIPELINE_SUMMARY_AND_WEAKNESSES.md (imperative baseline)
│   └── docs/functional_programming/
│       ├── FUNCTIONAL_ANALYSIS.md (refactor summary + Z-set findings)
│       ├── FUNCTIONAL_CONCEPTS.md (FP concept catalog)
│       ├── Z-SET_USAGE.md (Z-set calculation walkthrough)
│       └── IMPERATIVE_VS_FUNCTIONAL.md (balanced comparison)
│
└── docs/*.html (interactive browser tools)
```
