# Swing Allocator v7 Cycle Core — certified results

## Status

`CERTIFIED_CAUSAL_CANDIDATE`, inactive. V7 does not replace the frozen v6-2 default,
authorize paper activation, or authorize Demo/live trading.

## Valid same-contract comparison

Both rows use normalized BTC-USDT 1H data: exact duplicate candles are collapsed,
conflicting/out-of-order candles fail closed, the window is UTC 2015-01-01 through
2026-01-01, warmup is 6,000 bars (250 days), and execution is completed UTC 4H
decisions with next-open fills, 0.10% fee, and 5 bps slippage.

| Strategy | Final capital from $10,000 | CAGR | Max drawdown | Calmar | Operations | Interpretation |
|---|---:|---:|---:|---:|---:|---|
| **V7 Cycle Core** | **$54,002,022.19** | **118.42%** | -70.49% | **1.68** | 6 | Certified/reference reconciliation `PASS` |
| **BTC buy & hold** | $2,731,291.11 | 66.61% | -83.77% | 0.80 | 1 | Matched benchmark; V7 final capital is 19.77× higher and drawdown is 13.28pp lower |

The authoritative V7 replay is timestamp-based, next-open, fee-reserved, and has
six operations. The final capital is `$54,002,022.18728089349690`; the corrected
reference and certification artifacts are on `codex/universal-certification-gate`
at commit `98fb5ca`.

## V6-2 context

| Strategy | Final capital | CAGR | Max drawdown | Calmar | Meaning |
|---|---:|---:|---:|---:|---|
| Swing v6-2 frozen default | $9.505M | 86.51% | **-52.73%** | 1.64 | Protected historical-input reference; useful risk context, not a matched causal V7 benchmark |

## Limits

The historical sample contains only two complete modern cycles. The halving calendar
is a precommitted rule, but the result remains historical—not forward evidence. The
candidate stays inactive pending an explicitly approved isolated-paper setup and
forward observation.
