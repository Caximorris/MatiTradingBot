---
name: quant-research-signals
description: Research and compare indicators, features, market structure, regime definitions, and signal statistics for systematic trading. Use for indicator research, feature ablation, regime detection, market-structure analysis, signal decay, threshold-free ranking, or comparison of predictive signals before strategy integration.
---

# Quant Signal Research

## Purpose

Determine whether an indicator, feature, regime, or market-structure claim contains stable,
point-in-time information before it is embedded in entry, exit, sizing, or allocation logic.

## Trigger Conditions

Use for comparing indicators, defining regimes, researching market structure, measuring conditional
returns, signal decay, coverage, redundancy, or structural interpretation of a feature.

## When Not to Use

- Do not optimize a complete strategy, implement order logic, or promote a signal to default.
- Do not use descriptive correlation alone as proof of tradable edge.
- Do not add indicators outside `strategies/indicators.py` or duplicate the legacy
  `data/indicators.py` implementation.

## Required Context

Read `../quant-orchestrate-research/references/research-contract.md` and
`../quant-orchestrate-research/references/project-surface.md`. Read the preregistered hypothesis.
Inspect `strategies/indicators.py`, its direct consumers, resampling logic, relevant contexts, and
tests.

## Workflow

1. Define the feature mathematically, including units, lookback, timestamp meaning, availability
   lag, missing-value policy, warmup, and expected causal mechanism.
2. Validate source data and time alignment with `$quant-validate-data` before measuring outcomes.
3. Prefer continuous/ranked analysis before thresholds. Measure coverage, distribution, stability,
   autocorrelation, turnover, and redundancy with existing features.
4. Compare forward returns or strategy-independent outcomes across quantiles and horizons. Separate
   overlapping horizons and correct uncertainty for serial dependence when necessary.
5. Segment by predeclared regimes, cycles, venues, and costs without choosing segments after seeing
   winners. Report the number of independent events, not only bar count.
6. Run ablation against the simplest benchmark and compare equal information sets.
7. Treat threshold selection as robustness work; hand off to `$quant-test-robustness`.
8. If the signal survives, hand a precise feature contract to `$quant-engineer-strategy`.

## Verification Steps

- Prove no incomplete daily, weekly, or 4H bar enters an intraday decision.
- Check lookback/warmup truncation, shift direction, resample labels, timezone, and external-data lag.
- Confirm comparisons use identical timestamps and missing-data masks.
- Check multiple comparisons, event dependence, regime imbalance, and effect concentration.
- Confirm economic magnitude survives realistic turnover and costs, not just statistical significance.

## Expected Output

Produce a signal card with definition, mechanism, availability, coverage, descriptive distribution,
quantile/conditional outcome table, decay curve, regime stability, redundancy, cost sensitivity,
sample limitations, and verdict: `SUPPORTED`, `REJECTED`, or `INCONCLUSIVE`.

## Success Criteria

- The signal is point-in-time valid and reproducible from named data and code.
- Its effect is stable enough to survive reasonable lags, horizons, and regimes.
- Any chosen threshold lies on a robust plateau and is not selected from the final test set.
