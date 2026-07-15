---
name: quant-validate-data
description: Validate research datasets and market data for systematic trading. Use for dataset audits, missing or duplicate data detection, timestamp and timezone alignment, exchange consistency, timeframe/resample consistency, point-in-time availability, survivorship bias, stale external context, cache determinism, or unexplained candle-count differences.
---

# Quant Data Validation

## Purpose

Decide whether a dataset is fit for a stated research claim without silently repairing or mutating
canonical evidence.

## Trigger Conditions

Use when data integrity, missingness, duplication, alignment, venue consistency, timeframe
consistency, survivorship, stale context, deterministic caching, or candle counts are in question.

## When Not to Use

- Do not judge strategy profitability or simulator execution correctness.
- Do not delete, deduplicate, extend, truncate, or redownload canonical caches during forward test.
- Do not treat expected exchange outages or identical seam duplicates as strategy failures.

## Required Context

Read `../quant-orchestrate-research/references/research-contract.md` and
`../quant-orchestrate-research/references/project-surface.md`. Inspect `data/ohlcv_cache.py`,
`data/market_data.py`, `core/backtest.py:fetch_historical_bars`, relevant context loaders,
`tools/data_audit.py`, and their tests. Do not open `.env` or raw runtime artifacts.

## Workflow

1. Define the dataset contract: symbol/universe, venue, instrument type, bar interval, UTC coverage,
   expected cadence, columns/units, corporate/listing rules, and point-in-time availability.
2. Inventory source lineage, fallbacks, cache metadata, transforms, warmup, resamples, joins, and
   missing-data/default behavior.
3. Run the existing read-only `python main.py data-audit` where applicable. Inspect tool behavior
   first and avoid live probes unless the request explicitly requires current venue comparison.
4. Measure sortedness, duplicates, conflicting duplicates, gaps, zero/negative/impossible OHLCV,
   timestamp boundaries, coverage, and deterministic repeated slices.
5. Verify resampling labels and closed-bar exclusion across 1H/4H/daily/weekly data.
6. Verify cross-source joins are as-of joins with conservative lags. Flag silent neutral/default
   degradation separately from missing raw data.
7. For multi-asset research, audit delistings, listing-date truncation, symbol mapping, and universe
   membership through time. State when survivorship cannot be ruled out.
8. Classify each finding as data defect, known artifact, source limitation, or research limitation.

## Verification Steps

- Confirm two identical cached requests return identical candle counts and timestamp hashes/slices.
- Confirm candidate and baseline use the same actual timestamps, not merely the same date strings.
- Confirm OHLC invariants, volume units, timezone, bar boundaries, and monotonic ordering.
- Confirm external features are lagged to when they were actually knowable.
- Confirm the audit made no cache/runtime writes and review `git status` afterward.

## Expected Output

Produce a dataset card: lineage, schema, coverage, counts/distinct counts, gaps, duplicates/conflicts,
freshness, alignment, point-in-time rules, venue/timeframe comparison, survivorship status,
determinism evidence, known limitations, and verdict `FIT`, `FIT_WITH_LIMITATIONS`, or `NOT_FIT`.

## Success Criteria

- Every downstream run can identify the exact dataset and timestamps used.
- Known artifacts are visible and not silently repaired.
- Material leakage, alignment, or survivorship risks block strategy conclusions.
