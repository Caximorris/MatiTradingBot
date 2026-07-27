# V7 completed bootstrap checkpoint

Classification: research-only. This document records the completed fixed-seed stress diagnostic; it is not forward or out-of-sample evidence.

## Completion proof

- Scheduled primary cases: 4,000.
- Terminal primary cases: 4,000.
- Pending primary cases: 0.
- Eight method/block cells, 500 primary replications each.
- Failed and invalid cases: 0.
- Master seed: `20260727`.

## Stress result

All 4,000 paths exceeded 99% maximum drawdown; 1,971/4,000 (49.3%) had negative CAGR. The 95% Wilson interval for that loss frequency is 47.7%–50.8%.

| Family | CAGR p05 / p50 / p95 | Negative CAGR |
|---|---:|---:|
| Moving 24h | -49.85% / 0.03% / 104.38% | 249/500 |
| Moving 72h | -50.51% / 1.90% / 106.50% | 242/500 |
| Moving 168h | -52.33% / -2.03% / 109.86% | 264/500 |
| Moving 720h | -52.55% / 3.70% / 98.57% | 233/500 |
| Stationary 24h | -50.83% / 3.94% / 109.89% | 233/500 |
| Stationary 72h | -48.42% / 1.77% / 91.80% | 241/500 |
| Stationary 168h | -51.31% / 0.98% / 95.39% | 244/500 |
| Stationary 720h | -51.47% / -2.76% / 108.80% | 265/500 |

## Interpretation limit

Blocks preserve local OHLC dependence but are timestamp-rebased under the fixed halving/phase calendar. They therefore break the economic relationship between historical cycle phase and price path. Treat these outputs as market-path stress conditional on a fixed calendar, never as forward loss probabilities.

## Verdict impact

`STATISTICAL_ROBUSTNESS = FRAGILE`. `COMPARATOR_INTEGRITY` remains `BLOCKED_UNAVAILABLE_EVIDENCE`: the protected V6-2 funding input is absent and no archival metric may be substituted.
