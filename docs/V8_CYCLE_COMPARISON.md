# V8 cycle comparison — 2018 accumulation start

## Status

[Certain] This is a research-only comparison. It does not replace Swing v6-2, modify the V8 paper/Demo structure, authorize V8 activation, or authorize live trading.

## Frozen run contract

| Field | Value |
|---|---|
| Window | 2018-12-26 00:00 UTC through 2026-06-30 23:00 UTC |
| Start rationale | First accumulation day after the confirmed 2016 halving |
| Symbol / interval | BTC-USDT / 1H |
| Initial capital | $10,000 |
| Cost proxy | 10 bps fee plus 5 bps adverse slippage per fill leg |
| Warmup | 250 days / 6,000 bars for V6 |
| Tested bars | 65,856 |
| Canonical source | Protected BTC-USDT 1H cache through 2026-01-01 23:00 UTC; 67,536 rows including warmup |
| Extension | In-memory Binance Vision BTCUSDT 1H data from 2026-01-02 through 2026-06-30; 4,320 rows |
| Cache mutation | None |

The Binance archive used microsecond timestamps; they were converted to UTC milliseconds before validation. The combined series was strictly sorted, had no duplicates or gaps, and passed OHLC invariants. It is a cross-venue research seam, so it cannot recertify protected V6 historical anchors.

## Results

| Strategy | Contract | Final | Return | CAGR | Max DD | Calmar | Events | Verdict |
|---|---|---:|---:|---:|---:|---:|---:|---|
| V6 current-input control | Repository spot engine; v5-equivalent router; funding overlay off | $236,751 | 2,267.51% | 52.40% | -54.89% | 0.95 | 186 fills / 95 trades | Valid current-input control, not protected v6-2 |
| BTC buy & hold | One spot purchase under the same fee/slippage proxy | $156,415 | 1,464.15% | 44.22% | -77.19% | 0.57 | 1 | Matched benchmark |
| V7 phase-policy replay | 100% BTC except 0% during bear-onset | $896,586 | 8,865.86% | 81.93% | -70.51% | 1.16 | 4 | Policy-only replay |
| V8 schedule proxy | Long 2x outside bear-onset; short 2x inside it | $14,267,352 | 142,573.52% | 162.95% | -81.42% | 2.00 | 4 | Under-modeled research proxy |

V8 transition fills were 2018-12-26 18:00 UTC long 2x, 2021-11-02 21:00 UTC short 2x, 2022-10-28 21:00 UTC long 2x, and 2025-10-12 02:00 UTC short 2x. The proxy fails at non-positive intrabar equity, but it does **not** model historical funding payments, OKX maintenance-margin tiers, liquidation fees, funding settlement timing, or actual X-Perp liquidity.

## Material limitations

[Certain] The V7 state-machine replay on this start window entered the first accumulation position and then locked with `filled_order_target_unreached`. The policy row is therefore not a certified V7 state-machine backtest.

[Certain] V8’s operational service is designed for safe isolated Demo execution, not historical P&L simulation. The V8 row is intentionally not a deployment or adoption claim.

[Likely] A calibrated perpetual model with historical funding and tier-aware liquidation will reduce or invalidate the V8 proxy result. The -81.42% drawdown already exceeds V6 and buy-and-hold is not a risk improvement.

## Next decisive work

1. Repair and regression-test the V7 restart-window reconciliation defect without changing its frozen policy.
2. Build a separate V8 historical perpetual accounting model with timestamped funding, maintenance margin, liquidation fees, tick/lot rounding, and the exact target/fill timeline.
3. Repeat the same matrix under realistic and conservative costs, then perform robustness and execution review before any default decision.
