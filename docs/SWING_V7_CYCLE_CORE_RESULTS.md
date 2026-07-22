# Swing Allocator v7 Cycle Core — results

## Verdict

`NEEDS_MORE_VALIDATION`.  V7 was implemented and the frozen current-input suite
completed, but its historical advantage is an in-sample calendar rule with only two
completed modern cycles.  It cannot replace v6-2 or receive capital without forward
shadow evidence and explicit approval.

## Provenance and control

The historical $9,505,067.92 v6-2 result is
`ARCHIVAL_NON_REPRODUCIBLE_REFERENCE`: no exact funding snapshot plus manifest/slice
package was recovered.  The local Bybit snapshot has SHA-256
`23cc1952a9eed3806fb6f91e9cfdd788d0ae1dcfcc244524ea3f904b4497685f`, but is explicitly
not the protected input.  Overlay-on v6 fails closed and was retained as a failed
diagnostic, not substituted silently.

The executable current control is therefore frozen v6 code with the overlay explicitly
disabled, labelled `V6_CURRENT_INPUTS_REPRODUCIBLE_FALLBACK`.  Its legacy cadence is
reported beside a UTC-four-hour shared-cadence control.  This is not a reproduction of
the archival v6-2 headline.

The canonical file SHA-256 before and after the suite is
`284b26b68fda8931642a0fd7286a68d806dbf2adcd3d318313a395149d2a073f`.
It contains 102,931 stored rows, 102,457 distinct timestamps and 474 protected exact
duplicates.  The requested 2015-01-01T00:00Z through 2026-01-01T00:00Z inclusive
slice contains 96,907 rows; the historical 102,930 versus 102,931 difference is an
endpoint/observation-count discrepancy, not a cache rewrite.

## A–F, realistic costs

| Case | Final capital | CAGR | Max DD | Calmar | Orders | Fees |
|---|---:|---:|---:|---:|---:|---:|
| A BTC buy-and-hold | $2.733M | 66.53% | -83.77% | 0.79 | 1 | $9.95 |
| B v6 reproducible fallback | $9.138M | 85.84% | -52.73% | 1.63 | 137 | $92.1k |
| B v6 shared cadence | $8.455M | 84.54% | -53.15% | 1.59 | 138 | $86.8k |
| C v6 without EMA50 cap | $8.442M | 84.51% | -52.73% | 1.60 | 108 | $78.7k |
| D bull-phase hold | $12.082M | 90.62% | -52.73% | 1.72 | 107 | $73.7k |
| E v7 Cycle Core | $47.863M | 116.04% | -70.43% | 1.65 | 6 | $66.8k |
| F v7 bear 20% | $30.270M | 107.22% | -70.44% | 1.52 | 240 | $44.4k |

`Order` and `fill` are execution events; `rebalance decision` is an evaluated target;
`trade` is the engine's accounting event; `transition` is an idempotent phase-state
change.  The historical 137 versus 70 discrepancy is therefore not contradictory:
the former is rebalance/order-event accounting while the latter is ACB trade accounting.

## Phase attribution for v7

Each segment normalizes strategy and BTC equity to 1.0 at its own start.  Relative
performance is `(strategy_end/strategy_start)/(btc_end/btc_start)`; prior segment gains
do not carry forward.  Risk-on phases are close to BTC less transition costs, while
complete bear-onset segments contribute the material protection: 2017–18 = 3.71x and
2021–22 = 3.12x relative to BTC.  The partial 2015 bear segment is 1.33x and the
incomplete 2025 bear segment is 1.29x.

Non-bear relative results ranged from 0.905 to 1.042 across complete segments, which
is consistent with the no-tactical-trading design plus execution timing/costs.

## Sensitivity, stress, and placebos

The 3x3 final-capital matrix is:

| Bear start / accumulation start | 840 | 900 | 960 |
|---|---:|---:|---:|
| 480 | $10.026M | $20.289M | $17.919M |
| 540 | $23.650M | $47.863M | $42.272M |
| 600 | $11.996M | $24.276M | $21.440M |

All nine cells exceed buy-and-hold, but dispersion is large ($10.026M–$47.863M): this
is not a broad enough plateau to infer a stable natural 540/900 law.

Costs were resilient mechanically: realistic $47.863M, conservative $47.707M, and
twice-conservative $47.318M.  Delays did not destroy the historical result (1h
$48.066M; 6h $48.115M; 12h $50.954M; 24h $53.537M; 72h $54.528M), but some delays
improving the result is adverse evidence of calendar sensitivity, not validation.

Actual calendar final capital was $47.863M.  Placebos were $22.3k (-365d), $1.716M
(-180d), $1.869M (+180d), and $444k (+365d).  Actual dates outranked all four, but
this is an in-sample placebo observation, not proof of causality.

## Operational and statistical limitations

V7 uses a separate immutable confirmed-halving clock, UTC 4-hour decision blocks,
and persisted `ERROR_LOCKED` transition states.  Open/submitted orders cannot be
resubmitted without explicit reconciliation.  No v6 file or default changed.

CSCV/PBO and Deflated Sharpe are intentionally not reported: treating hourly candles
as independent observations would be methodologically false with only two complete
modern cycles.  The 2024 cycle is incomplete.  All results are exploratory and the
candidate remains disabled by default; no paper/shadow/live instance was activated.

Detailed resumable case evidence, manifests and completion proof are in
`backtests/v7_cycle_core/`.
