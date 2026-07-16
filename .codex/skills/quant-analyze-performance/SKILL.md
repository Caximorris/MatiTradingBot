---
name: quant-analyze-performance
description: Analyze systematic-trading performance and risk from validated results. Use for equity-curve analysis, drawdown and underwater analysis, trade or rebalance distribution, expectancy, risk metrics, Sharpe, Sortino, Calmar/MAR, CAGR, return concentration, exposure, turnover, monthly/annual attribution, or allocator-versus-buy-and-hold diagnostics.
---

# Quant Performance Analysis

## Purpose

Explain where returns and risk came from without confusing descriptive metrics with evidence of
generalization.

## Trigger Conditions

Use for equity curves, drawdowns, trade distributions, expectancy, Sharpe, Sortino, Calmar/MAR,
CAGR, concentration, exposure, turnover, attribution, or benchmark-relative diagnostics.

## When Not to Use

- Do not analyze an invalid dataset/backtest as if its metrics were trustworthy.
- Do not use performance ratios alone to claim robustness or select parameters.
- Do not interpret allocator PF/WR like independent closed-trade strategy statistics.
- Do not set risk appetite or sizing limits; hand prescriptive risk questions to `$quant-design-risk`.

## Required Context

Read `../quant-orchestrate-research/references/research-contract.md`,
`../quant-orchestrate-research/references/project-surface.md`, and the integrity verdicts. Inspect
`BacktestResult` metric definitions, timeframe, exact journal summary, output type in
`strategies/registry.py`, and available reporting tools such as `monthly_dist.py`,
`backtest_report.py`, and `strategy_audit.py`.

## Workflow

1. Identify metric definitions, sampling frequency, annualization, benchmark, cash flows, costs,
   open-position treatment, and whether the artifact is trade-based or allocator-based.
2. Reconstruct the equity curve and verify start/end balances before interpreting ratios.
3. Decompose return by calendar period, regime/cycle, side, exit/rebalance reason, exposure, and
   instrument where supported by the data.
4. Analyze drawdown depth, duration, recovery, underwater distribution, worst episodes, and whether
   losses align with declared risk assumptions.
5. Analyze trade/event distribution: expectancy, median, tails, skew, win/loss sizes, streaks,
   holding time, MAE/MFE when available, and profit concentration by top trades/periods.
6. Report CAGR, Sharpe, Sortino, Calmar/MAR, volatility/downside deviation, time in market, turnover,
   and benchmark-relative results with definitions and limitations.
7. For allocators, emphasize exposure path, churn, BTC accumulation, `final_btc_qty`,
   `bnh_initial_btc`, and `btc_vs_bnh_ratio`; label PF as accounting-fragile.
8. Separate arithmetic observations from causal explanations. Hand generalization claims to
   `$quant-test-robustness` and risk mandates to `$quant-design-risk`.

## Verification Steps

- Reconcile final equity, total return, and CAGR from raw start/end/time span.
- Recompute peak-to-trough Max DD and longest underwater interval from the equity curve.
- Check annualization matches the return sampling and timeframe.
- Check sample size, serial dependence, zero-volatility cases, open trades, and outlier concentration.
- Confirm benchmark and candidate share currency, window, costs, and cash-flow assumptions.

## Expected Output

Produce a performance tear sheet with identity block, headline metrics, equity/drawdown diagnosis,
distribution and concentration, period/regime attribution, benchmark comparison, allocator-specific
inventory when relevant, limitations, and descriptive verdict `HEALTHY`, `CONCENTRATED`,
`ASYMMETRIC_RISK`, or `INSUFFICIENT_SAMPLE`.

## Success Criteria

- Headline metrics reconcile and their definitions are explicit.
- The report identifies the dominant return sources and worst risk episodes.
- Descriptive strength is not misrepresented as OOS robustness or production readiness.
