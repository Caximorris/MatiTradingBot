---
name: mati-swing-validator
description: Validate MatiTradingBot Swing Allocator experiments, journals, and strategy changes. Use when working on Swing Allocator, BTC allocation, drawdown/exposure tests, backtest comparison, `min_btc_pct`, `max_btc_pct`, `regime_off_on_bear_onset`, or any request to promote a Swing candidate to default.
---

# Mati Swing Validator

## Required Context

Read `AGENTS.md`, `SESSION.md`, `backtests/STRATEGY_VERSIONS.md`, and `SWING_PLAN.md` before changing code or drawing conclusions.

If the task is a comparison or validation, also read `references/swing-protocol.md`.

## Operating Rules

- Treat Swing Allocator v3 as the current default.
- Do not touch `strategies/pro_trend.py` unless the user explicitly changes focus away from Swing.
- Do not promote a candidate because it improves one window or one metric.
- Do not compare runs with different candle counts, windows, or cost modes.
- Use BTC 2015-01-01 to 2026-01-01 realistic as the primary window.
- Use BTC 2018-01-01 to 2026-01-01 realistic as the secondary recent-market window.
- Run conservative costs for final candidates.
- Report `final_btc_qty`, `bnh_initial_btc`, and `btc_vs_bnh_ratio` for every Swing candidate.
- Treat PF as fragile; make CAGR and Max DD the primary anchors.

## Current Baseline

Swing Allocator v3:

- Config: `regime_off_on_bear_onset=True`, `bull_peak_ema50_cap_enabled=True`, `bull_peak_ema50_cap=0.85`, `use_regime=True`, `use_halving=True`, other signal toggles false.
- BTC 2015-2026 realistic: $6.998M, CAGR +81.39%, Max DD -53.64%, PF 6.10, `btc_vs_bnh_ratio=0.8531`.
- BTC 2018-2026 realistic: $174.8k, CAGR +42.99%, Max DD -53.42%, PF 5.55, `btc_vs_bnh_ratio=0.9140`.
- BTC 2015-2026 conservative: $6.806M, CAGR +80.93%, Max DD -53.69%, PF 5.84, `btc_vs_bnh_ratio=0.8301`.
- Risk note: Q4 2025 is worse than v2 (+$290k -> -$42.6k in the 2015 realistic run), so do not add another late-cycle flag without per-cycle attribution.
- Rollback v2: `--config '{"bull_peak_ema50_cap_enabled": false}'`.
- Rollback v1: `--config '{"regime_off_on_bear_onset": false}'`.

## Candidate Queue

Recent decision:

- `bull_peak_ema50_cap_enabled=True`, cap `0.85`: adopted as v3. It caps target exposure only during `bull_peak` after BTC loses the previous full day's EMA50D. It keeps `min_btc_pct=0.30`, improves 2015 realistic and 2018 realistic anchors, and survives 2015 conservative costs.
- `min_btc_pct=0.0`: passes USDT/DD anchors in 2015 realistic, 2018 realistic, and 2015 conservative, but sharply reduces final BTC vs B&H versus v2. User chose to keep one strategy and refine v2 instead of splitting into a USDT-max variant. Do not promote it as default.

Discarded:

- Global `max_btc_pct=0.90`, `0.80`, `0.70`: lower exposure but kill CAGR.
- Todo-o-nada allocation: worse than v2 and incompatible with gradual accumulation.
- Suppress all regime signals during `bear_onset`: breaks 2022 by disabling `regime_bear`.

Next focus:

- Do not add more flags immediately. Audit `bull_peak_ema50_cap_*` events and compare v3 vs v2 by cycle first.
- Keep future changes isolated, reversible, and compatible with `min_btc_pct=0.30`.

## Output Shape

Lead with the uncomfortable answer. Use `[Certain]`, `[Likely]`, or `[Guessing]` before claims.

For comparisons, produce a table with:

- Config
- Window
- Cost mode
- Candle count, if available
- Final balance
- CAGR
- Max DD
- PF
- Rebalances/trades
- `final_btc_qty`
- `btc_vs_bnh_ratio`
- Verdict

Verdicts must be one of: `ADOPT`, `REJECT`, `NEEDS_MORE_VALIDATION`.
