# Swing Validation Protocol

## Baseline

Current default is Swing Allocator v3.

Baseline anchors:

- BTC 2015-2026 realistic: $6.998M, CAGR +81.39%, Max DD -53.64%, PF 6.10, `btc_vs_bnh_ratio=0.8531`.
- BTC 2018-2026 realistic: $174.8k, CAGR +42.99%, Max DD -53.42%, PF 5.55, `btc_vs_bnh_ratio=0.9140`.
- BTC 2015-2026 conservative: $6.806M, CAGR +80.93%, Max DD -53.69%, PF 5.84, `btc_vs_bnh_ratio=0.8301`.
- v3 = v2 plus `bull_peak_ema50_cap_enabled=True`, cap `0.85`.
- Rollback v2: `--config '{"bull_peak_ema50_cap_enabled": false}'`.
- Q4 2025 is worse than v2 in the 2015 realistic run (+$290k -> -$42.6k), but the full-window CAGR/DD/BTC anchors improve.

## Metrics

Primary:

- CAGR
- Max DD
- Final balance
- `btc_vs_bnh_ratio`

Secondary:

- PF
- Win rate
- Rebalance count
- Q4 2025 contribution

PF is fragile because it changes heavily with start date. Never use PF alone as the verdict.

## Required Validation

Before changing a default:

1. BTC 2015-2026 realistic must improve or maintain CAGR/DD.
2. BTC 2018-2026 realistic must not break.
3. Conservative costs must not invalidate the result.
4. If `btc_vs_bnh_ratio` deteriorates, say so explicitly.
5. If the result depends on one cycle or one avoided rebalance cluster, mark it as overfitting risk.

## Recent Decision

`bull_peak_ema50_cap_enabled=True`, `bull_peak_ema50_cap=0.85`:

- 2015-2026 realistic: $6.998M, CAGR +81.39%, Max DD -53.64%, PF 6.10, `btc_vs_bnh_ratio=0.8531`.
- 2018-2026 realistic: $174.8k, CAGR +42.99%, Max DD -53.42%, PF 5.55, `btc_vs_bnh_ratio=0.9140`.
- 2015-2026 conservative: $6.806M, CAGR +80.93%, Max DD -53.69%, PF 5.84, `btc_vs_bnh_ratio=0.8301`.
- Adopted as v3 because it improves the primary and secondary windows and survives conservative costs while keeping `min_btc_pct=0.30`.

`min_btc_pct=0.0`:

- 2015-2026 realistic: $7.56M, CAGR +82.66%, Max DD -53.41%, PF 4.78, `btc_vs_bnh_ratio=0.5162`.
- 2018-2026 realistic: $186k, CAGR +44.14%, Max DD -53.42%, PF 4.52, `btc_vs_bnh_ratio=0.5410`.
- 2015-2026 conservative: $7.36M, CAGR +82.24%, Max DD -53.47%, PF 4.65, `btc_vs_bnh_ratio=0.5033`.
- Actual minimum exposure was about 20%, not zero, because base + deltas do not always hit the hard floor.
- It improves USDT CAGR/DD versus v2, but worsens final BTC holdings versus v2.
- User decision: keep v2 as one strategy, do not split into a separate USDT-max profile, and do not promote `min_btc_pct=0.0`.

## Next Focus

Refine v3 without changing the hard BTC floor:

1. Keep `min_btc_pct=0.30`.
2. Avoid global `max_btc_pct` caps.
3. Before adding another flag, audit `bull_peak_ema50_cap_*` events by cycle against v2.
4. Test one isolated, reversible hypothesis at a time.

## Commands

PowerShell examples:

```powershell
python main.py backtest --strategy swing --from 2015-01-01 --to 2026-01-01 --costs realistic --config '{"min_btc_pct": 0.0}'
python main.py backtest --strategy swing --from 2018-01-01 --to 2026-01-01 --costs realistic --config '{"min_btc_pct": 0.0}'
python main.py backtest --strategy swing --from 2015-01-01 --to 2026-01-01 --costs conservative --config '{"min_btc_pct": 0.0}'
python main.py backtest --strategy swing --from 2015-01-01 --to 2026-01-01 --costs realistic --config '{"bull_peak_ema50_cap_enabled": false}'
```
