---
name: mati-swing-validator
description: Validate MatiTradingBot Swing Allocator experiments, journals, strategy changes, and promotion decisions. Use for Swing Allocator, BTC allocation, drawdown/exposure tests, backtest comparison, phase policies, funding overlays, v5/v6, `min_btc_pct`, `max_btc_pct`, `regime_off_on_bear_onset`, or any request to promote a Swing candidate to default.
---

# Mati Swing Validator

## Purpose

Apply the project-specific Swing Allocator evidence, rollback, and promotion gates after generic data,
backtest, performance, and robustness validation. This is the final domain gate, not a general
research or implementation skill.

## Trigger Conditions

Use for every Swing Allocator experiment, comparison, journal review, v5/v6 question, funding
overlay, BTC allocation/exposure test, drawdown investigation, or promotion/default decision.

## When Not to Use

- Do not use as the only skill for data integrity, simulator bias, statistics, or code quality.
- Do not use for Pro Trend or unrelated strategies.
- Do not treat historical improvement as authorization for live trading or another closed-sample
  exception.

## Required Context

Read `AGENTS.md`, `SESSION.md`, `backtests/STRATEGY_VERSIONS.md`, `EXPERIMENTS.md`, and
`docs/swing/plan.md` before changing code or drawing conclusions. For v6 work, also read
`docs/swing/v6-plan.md`. For comparison, validation, or promotion, read
`references/swing-protocol.md`.

Also apply the relevant generic skills: `$quant-validate-data`, `$quant-audit-backtest`,
`$quant-analyze-performance`, and `$quant-test-robustness`. Use `$quant-run-experiment` to execute a
fixed matrix and `$quant-engineer-strategy` only when implementation was explicitly requested.

## Operating Rules

- Treat Swing Allocator v6-2 as the current frozen default; v5 is the rollback/control.
- Do not touch `strategies/pro_trend.py`.
- The 2015-2026 window is closed for optimization. It measures robustness but cannot by itself
  promote a future candidate.
- Compare only through the same harness with exact candles, window, costs, warmup, and funding data.
- Use BTC 2015-2026 realistic as the primary historical anchor, BTC 2018-2026 realistic as the
  secondary anchor, and conservative costs for finalists.
- Require forward/paper evidence after 2026-01-01 before future promotions. v6-2 is a documented,
  user-approved paper-only exception because v5 and v6 started forward validation together.
- Report `final_btc_qty`, `bnh_initial_btc`, and `btc_vs_bnh_ratio` for every candidate.
- Treat PF as fragile; use CAGR and Max DD as primary historical anchors.

## Current Baseline

Swing Allocator v6-2, frozen by explicit user decision on 2026-07-13:

- Config: v5 plus phase router `v5_equiv`, funding overlay delta `0.05`, p10/p90, TTL/dedup
  7 days, only in `accumulation`; `daily_on_closed_only=True`; `min_btc_pct=0.20`;
  `delta_bear_onset=-0.30`; bear-onset regime suppression and bull-peak EMA50 cap enabled.
- BTC 2015-2026 realistic: $9.505M, CAGR +86.51%, Max DD -52.73%, 70 ACB rebalances,
  `btc_vs_bnh_ratio=0.8499`.
- BTC 2018-2026 realistic: $229.0k, CAGR +47.90%, Max DD -53.72%, 53 ACB rebalances,
  `btc_vs_bnh_ratio=0.8785`.
- BTC 2015-2026 conservative: $9.255M, CAGR +86.06%, Max DD -52.88%, 70 ACB rebalances,
  `btc_vs_bnh_ratio=0.8281`.
- Exact v5 rollback: `--config '{"use_phase_policy_router": false, "use_funding_overlay": false}'`.

## Workflow

1. Identify the exact decision: measure, reject, continue forward observation, or promote.
2. Check `EXPERIMENTS.md` and Swing plans for closed or previously tested paths.
3. Freeze baseline/candidate configs, harness, dataset, windows, costs, metrics, and rollback.
4. Validate same candles and funding context, then audit point-in-time behavior and execution costs.
5. Run the smallest paired historical matrix needed; add conservative costs and rolling/regime tests
   only for finalists. Never use historical anchors to tune a new default.
6. Analyze CAGR, Max DD, BTC accumulation, exposure/churn, concentration, and forward evidence.
7. Apply the promotion gate in the bundled protocol. A historical-only candidate cannot be `ADOPT`.
8. Preserve v5 rollback/control and report funding freshness before accumulation.

## Verification Steps

- Confirm candle count, actual timestamps, window, warmup, cost mode, harness, and config are paired.
- Confirm current-day/incomplete bars and external contexts cannot leak into decisions.
- Confirm rollback reproduces the documented v5 behavior.
- Confirm event rebalances and ACB trades are not conflated.
- Confirm forward divergence is real strategy evidence rather than infrastructure/demo-price distortion.
- Review journals via summaries, relevant tests, git diff/status, and protected artifacts.

## Expected Output

For comparisons, produce a table with config, window, cost mode, candle count, final balance, CAGR,
Max DD, PF, rebalance events/ACB trades, `final_btc_qty`, `bnh_initial_btc`,
`btc_vs_bnh_ratio`, forward evidence, and verdict.

Verdicts are `ADOPT`, `REJECT`, or `NEEDS_MORE_VALIDATION`. Lead with the uncomfortable answer and
tag claims `[Certain]`, `[Likely]`, or `[Guessing]`.

## Success Criteria

- Every conclusion follows the exact paired harness and full Swing protocol.
- No closed-sample tuning or one-window promotion occurs.
- v5 rollback remains reproducible and operational risks such as stale funding remain visible.
- `ADOPT` is impossible without all historical gates plus real post-2026 evidence and explicit user
  authority; live trading still requires separate confirmation.
