---
name: data-analysis
description: Analyze tabular, longitudinal or statistical data in Python, R or SQL; use for cleaning, cohort derivation, modeling and reproducible results.
---

# Analysis with traceable results

Inspect the data dictionary, actual column types and a bounded sample before
writing an analysis. State the unit of observation, join keys, time window,
inclusion rules, missing-value codes and intended estimand. Preserve raw
inputs; derive outputs into a separate project directory.

Use DuckDB/Polars or chunked reads for large files; inspect Parquet schemas
before loading everything. SQL joins need explicit key cardinality checks
and before/after row counts. Distinguish duplicate records from repeated
measures. Dates, time zones, decimal precision and leading-zero identifiers
need deliberate parsing. Record filtering counts and exclusions.

For models, check distributions and assumptions appropriate to the design;
use participant/group-aware and time-aware splits when applicable. Fit
preprocessing on training data only. Distinguish association from causal
claims, exploratory from prespecified tests, observed from imputed values,
and statistical uncertainty from practical importance. Do not pick a
method merely because a package is installed. Keep seeds and package versions.

Deliver runnable scripts/notebooks, a compact methods note, labeled figures
and a result table with denominators/units and uncertainty where meaningful.
Verify a small known case and a clean execution; avoid exporting row-level
personal data when aggregates answer the request. Write output manifests
with input references, transformations, warnings and exact run commands.
Use the environment skill when creating or restoring project dependencies.

Offline tools include pandas, NumPy, SciPy, statsmodels, scikit-learn,
DuckDB, Polars and PyArrow; R includes tidyverse, data.table, survival,
lme4/lmerTest and mgcv. Database drivers alone do not provide access to a
host database or permission to query one.
