# Bitcoin Cycle Phase Audit Plan

## Decision

Determine whether the Swing Allocator reporting/phase boundaries 180, 540, and 900 days are
independently supported historical windows, approximate centers, or backtest-shaped assumptions.
This is `research-only`; it cannot change v6-2, v7, v7-L, live targets, or the canonical OHLCV cache.

## Preregistered rules

- Primary historical extrema: canonical UTC daily consensus, with source-level extrema retained.
- Retrospective top: maximum daily close and maximum intraday high between consecutive halvings.
- Retrospective bottom: minimum close and low after the retrospective top and before the next halving.
- Causal confirmation: 20% drawdown, 60 days without a new high, followed by a 20% recovery and
  60 days without a new low. These constants are fixed for status classification, not optimized.
- Consensus: median close; `CONFIRMED` requires at least three providers and <=1% close dispersion;
  >2% dispersion is `SOURCE_DISAGREEMENT`; fewer than two sources is insufficient coverage.
- Temporal agreement tolerance: +/-3 UTC dates. It is a reporting tolerance, not a parameter search.
- Primary strategy anchors, if run: same Swing harness, 2015-01-01--2026-01-01 realistic costs,
  then 2018-01-01--2026-01-01 and conservative costs. No automatic candidate selection.

## Gates

1. Block-level halving provenance and separate future estimate.
2. Source manifests, hashes, revisions, gaps, duplicate and impossible-candle checks.
3. All-cycle and 2016+ modern-only extrema tables; 2024 is incomplete/provisional.
4. Error distributions, MAD/bootstrap, leave-one-cycle-out, placebo calendars, and fixed 5x5.
5. Current-cycle immutable prediction record and daily evidence updates.
6. Explicit confidence cap: fewer than four complete cycles cannot produce `HIGH` confidence.

## Falsification criteria

The hypothesis is weakened or rejected if source disagreement is material, extrema are not stable
within a broad window, leave-one-cycle-out moves the center radically, placebos match the calendar,
or the sensitivity surface has only an isolated peak. Any proposed v8 must remain `RESEARCH_ONLY`
until backtest, placebo, LOCO, and shadow-mode gates plus explicit human approval are complete.
