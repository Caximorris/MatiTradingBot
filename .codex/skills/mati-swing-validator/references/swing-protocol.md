# Swing Validation Protocol

## Frozen Baseline

Current default: Swing Allocator v6-2. v5 is the rollback/control.

| Window | Cost | Final | CAGR | Max DD | ACB rebalances | BTC vs B&H |
|---|---|---:|---:|---:|---:|---:|
| BTC 2015-2026 | realistic | $9.505M | +86.51% | -52.73% | 70 | 0.8499 |
| BTC 2018-2026 | realistic | $229.0k | +47.90% | -53.72% | 53 | 0.8785 |
| BTC 2015-2026 | conservative | $9.255M | +86.06% | -52.88% | 70 | 0.8281 |

Compare baseline and candidate through the same harness, exact candles, and funding cache.

## Metrics

Primary historical anchors:

- CAGR
- Max DD
- Final balance
- `btc_vs_bnh_ratio`

Required inventory:

- candle count
- rebalance-event count and ACB-trade count
- `final_btc_qty`
- `bnh_initial_btc`
- cost mode and exact window

PF is secondary and fragile because it changes with start date and ACB grouping.

## Required Validation

Before changing the frozen v6 default in the future:

1. Run v6 and the candidate over identical candles and through the same tool.
2. BTC 2015-2026 realistic must not materially worsen CAGR or Max DD.
3. BTC 2018-2026 realistic must not break.
4. BTC 2015-2026 conservative must preserve the result after higher slippage.
5. `btc_vs_bnh_ratio` must not deteriorate by more than 0.03 absolute.
6. Rebalance events must not rise by more than 20% without a clear BTC-accumulation gain.
7. Phase shifts and rolling starts must not expose a single-cycle dependency.
8. There must be forward/paper evidence after 2026-01-01.

Historical improvements alone produce `NEEDS_MORE_VALIDATION`, never `ADOPT`. The one recorded
exception is v6-2: the user explicitly approved a paper-only promotion because v5 and v6 began
forward validation simultaneously and v6 passed every available robustness test. It does not
authorize live trading or create a precedent for another closed-sample promotion.

## Adopted v6 Configuration

v6-2 configuration:

```json
{
  "use_phase_policy_router": true,
  "phase_policy_profile": "v5_equiv",
  "use_funding_overlay": true,
  "funding_overlay_delta": 0.05,
  "funding_overlay_ttl_days": 7,
  "funding_overlay_dedup_days": 7,
  "funding_overlay_phases": "accumulation",
  "funding_low_pctile": 0.10,
  "funding_high_pctile": 0.90
}
```

Documented historical results:

| Window | Cost | v5 final | v6 final | CAGR v5/v6 | Max DD v5/v6 | BTC ratio v5/v6 |
|---|---|---:|---:|---:|---:|---:|
| 2015-2026 | realistic | $9.138M | $9.505M | 85.84 / 86.51 | -52.73 / -52.73 | 0.8171 / 0.8499 |
| 2018-2026 | realistic | $219.8k | $229.0k | 47.14 / 47.90 | -53.72 / -53.72 | 0.8432 / 0.8785 |
| 2015-2026 | conservative | $8.897M | $9.255M | 85.40 / 86.06 | -52.88 / -52.88 | 0.7961 / 0.8281 |

Rolling annual starts 2018-2024 were 8/8 non-reject, with improvement in 7/8. This is still
closed-sample evidence. The overlay only acts in `accumulation`; v5 and v6 are expected to remain
identical until roughly 2026-10-07.

Current verdict: `ADOPT`.

## Promotion Gate

Future `ADOPT` decisions require all historical gates plus real post-2026 divergence. For v6
operation, funding data must be fresh before accumulation begins; a stale cache silently degrades
the overlay to v5 and must trigger an operational alert. Keep v5 available as rollback/control.

## Commands

```powershell
python tools/swing_v5_freeze_report.py
python main.py backtest --strategy swing --from 2015-01-01 --to 2026-01-01 --costs realistic --config '{"use_phase_policy_router":true,"phase_policy_profile":"v5_equiv","use_funding_overlay":true,"funding_overlay_delta":0.05,"funding_overlay_ttl_days":7,"funding_overlay_dedup_days":7,"funding_overlay_phases":"accumulation","funding_low_pctile":0.10,"funding_high_pctile":0.90}'
python tools/swing_rolling_start_matrix.py --start-every-days 30 --costs realistic
```
