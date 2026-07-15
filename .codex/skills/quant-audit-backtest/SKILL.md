---
name: quant-audit-backtest
description: Audit a systematic-trading backtest or simulator for measurement integrity. Use for backtest verification, look-ahead bias, data leakage, event ordering, failure propagation, fill-contract implementation, funding/accounting, warmup, timezone, metrics, or suspiciously strong results. Use `quant-model-execution` separately to specify or calibrate fees, slippage, spread, impact, and venue fill assumptions.
---

# Quant Backtest Audit

## Purpose

Determine whether a reported result could have been produced by a feasible point-in-time strategy
under the declared execution and accounting assumptions.

## Trigger Conditions

Use for bias audits, simulator reviews, execution/fee/slippage/funding verification, fill timing,
warmup boundaries, accounting reconciliation, or a backtest result that appears inconsistent.

## When Not to Use

- Do not decide whether an economically valid strategy generalizes; use robustness testing.
- Do not repair strategy logic while auditing measurement.
- Do not change fee, slippage, look-ahead, or fill assumptions without explicit approval.

## Required Context

Read `../quant-orchestrate-research/references/research-contract.md`,
`../quant-orchestrate-research/references/project-surface.md`, and the data-validation verdict.
Inspect `core/backtest.py`, `cli/runner.py`, strategy data consumers, contexts, resampling, cache
code, relevant tests, exact resolved config, the `$quant-model-execution` contract, and a compact
journal summary. Never read a raw large journal.

## Workflow

1. Reconstruct the complete path: source timestamp -> transformed feature -> decision -> order ->
   fill -> balance/position -> equity -> metric.
2. Audit availability: current/incomplete bars, negative shifts, resample labels, future extrema,
   same-bar decision/fill, external publication lag, warmup leakage, and OOS boundary leakage.
3. Audit execution implementation against the declared contract: market/limit timing, next-bar
   assumptions, buy/sell slippage direction, partial
   fills, rejected orders, min size, balance reservation, short/funding behavior, and order sequence.
4. Audit costs: fee currency, fee on every leg, configured cost mode, spread/slippage, funding, and
   repeated turnover. Reconcile cost totals independently where feasible.
5. Audit accounting: weighted average cost, partial exits, open positions at end, equity valuation,
   cash/base balances, ACB trade semantics, and allocator rebalance semantics.
6. Audit metrics: annualization by timeframe, return sampling, drawdown sign/peak, zero-trade cases,
   and continuous balance across calendar boundaries.
7. Reproduce the smallest decisive case with existing unit tests or a new isolated test fixture.
8. Report findings by severity and block performance interpretation on any critical integrity issue.

## Verification Steps

- Pair candidate and baseline on exact candles, warmup, window, costs, config path, and harness.
- Verify the known previous-day offsets and exclusion of incomplete higher-timeframe bars.
- Verify fees and slippage numerically on representative BUY, SELL, partial exit, and rebalance fills.
- Reconcile final equity from balances and prices, then reconcile journal trades to engine totals.
- Run relevant backtest/client tests plus deterministic repeat checks and inspect the full diff.

## Expected Output

Produce an audit table with severity (`CRITICAL`, `HIGH`, `MEDIUM`, `LOW`), invariant, evidence,
file/line, impact direction, reproduction, and remediation boundary. End with `VALID`,
`VALID_WITH_LIMITATIONS`, or `INVALID` and list which downstream conclusions remain permissible.

## Success Criteria

- Every material path from data to metric is accounted for.
- A critical leak or accounting defect invalidates the result even if returns improve.
- The audit itself does not mutate canonical data or production behavior.
