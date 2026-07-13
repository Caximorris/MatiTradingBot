---
name: mati-swing-validator
description: Validate MatiTradingBot Swing Allocator experiments, journals, and strategy changes. Use when working on Swing Allocator, BTC allocation, drawdown/exposure tests, backtest comparison, funding overlays, v5/v6, or any request to promote a Swing candidate to default.
---

# Mati Swing Validator

## Required Context

Read `AGENTS.md`, `SESSION.md`, `backtests/STRATEGY_VERSIONS.md`, and
`docs/swing/plan.md` before changing code or drawing conclusions. For v6 work, also read
`docs/swing/v6-plan.md`.

If the task is a comparison or validation, also read `references/swing-protocol.md`.

## Operating Rules

- Treat Swing Allocator v6-2 as the current frozen default; v5 is the rollback/control.
- Do not touch `strategies/pro_trend.py` unless the user explicitly changes focus away from Swing.
- The 2015-2026 window is closed for optimization. It measures robustness but cannot by itself promote a candidate.
- Do not promote a candidate because it improves one window or one metric.
- Do not compare runs with different candle counts, windows, cost modes, or execution paths.
- Use BTC 2015-01-01 to 2026-01-01 realistic as the primary historical anchor.
- Use BTC 2018-01-01 to 2026-01-01 realistic as the secondary historical anchor.
- Run conservative costs for final candidates.
- Require forward/paper evidence after 2026-01-01 before future promotions. v6-2 is a documented,
  user-approved paper-only exception because v5 and v6 started forward validation together.
- Report `final_btc_qty`, `bnh_initial_btc`, and `btc_vs_bnh_ratio` for every candidate.
- Treat PF as fragile; make CAGR and Max DD the primary historical anchors.

## Current Baseline

Swing Allocator v6-2, frozen by explicit user decision on 2026-07-13:

- Config: v5 plus `use_phase_policy_router=True`, `phase_policy_profile="v5_equiv"`,
  `use_funding_overlay=True`, delta `0.05`, p10/p90, TTL/dedup 7 days, only in
  `accumulation`; `daily_on_closed_only=True`; `min_btc_pct=0.20`,
  `delta_bear_onset=-0.30`, `regime_off_on_bear_onset=True`,
  `bull_peak_ema50_cap_enabled=True`, `bull_peak_ema50_cap=0.85`,
  `use_regime=True`, `use_halving=True`, other signal toggles false.
- BTC 2015-2026 realistic: $9.505M, CAGR +86.51%, Max DD -52.73%,
  70 ACB rebalances, `btc_vs_bnh_ratio=0.8499`.
- BTC 2018-2026 realistic: $229.0k, CAGR +47.90%, Max DD -53.72%,
  53 ACB rebalances, `btc_vs_bnh_ratio=0.8785`.
- BTC 2015-2026 conservative: $9.255M, CAGR +86.06%, Max DD -52.88%,
  70 ACB rebalances, `btc_vs_bnh_ratio=0.8281`.
- Rollback to v5: `--config '{"use_phase_policy_router": false, "use_funding_overlay": false}'`.

## Promotion Record

- v6-1 phase-policy router reproduced v5 exactly.
- v6-2 adds funding overlay `+0.05`, p10/p90, TTL 7 days, only in `accumulation`.
- v6-2 is `ADOPT`; v5 remains an isolated paper control and exact config rollback.
- v5 and v6 should be identical during `bear_onset`; expected first live divergence is around
  2026-10-07. Funding cache freshness on the VM must be reliable before that date.

Discarded or closed:

- Global `max_btc_pct=0.90/0.80/0.70`, all-or-nothing allocation, `min_btc_pct=0.0`
  as default, bull-peak cap latch, suppressing all regime signals in `bear_onset`, and shorts/perps.
- Max-DD and Q4-2025 parameter optimization fronts are closed without new forward evidence.

## Current Focus

- Finish F13/F15/F19 forward validation for the default and execution stack.
- Keep v5 and v6 isolated in paper so the rollback control remains measurable after divergence.
- Do not add flags or tune thresholds on the closed historical sample.
- Structural simplifications are allowed only when behavior is equivalent or anchors do not worsen.

## Output Shape

Lead with the uncomfortable answer. Use `[Certain]`, `[Likely]`, or `[Guessing]` before claims.

For comparisons, produce a table with:

- Config
- Window
- Cost mode
- Candle count
- Final balance
- CAGR
- Max DD
- PF
- Rebalances/trades
- `final_btc_qty`
- `bnh_initial_btc`
- `btc_vs_bnh_ratio`
- Verdict

Verdicts must be one of: `ADOPT`, `REJECT`, `NEEDS_MORE_VALIDATION`.
