# V7 Cycle Core — isolated paper readiness

## Decision

`PAPER_CANDIDATE_READY` as of 2026-07-23. This is an engineering and
historical-integrity gate for an inactive, isolated paper candidate. It is not
an `ADOPT` decision, default change, live/demo authorization, or evidence of a
durable edge.

## Frozen candidate contract

- Hypothesis: a fixed, confirmed-halving clock reduces exposure only during the
  precommitted 540–900-day bear-onset phase.
- Mechanism: target BTC is 100% in post-halving, bull-peak, and accumulation;
  it is 0% in bear onset. Decisions use a completed bar at UTC four-hour
  boundaries and causal fills at the subsequent 1H open.
- Expected failure: calendar boundaries may be selected in sample and fail to
  generalize across cycles or in forward paper observation.
- Backtest budget: the 29 predeclared V7-only causal cases in
  `tools/swing_cycle_core_suite.py`; no post-result parameter selection.
- Rollback: deactivate the isolated V7 instance. Preserve its separate wallet,
  transition journal, and database rows; do not delete evidence or alter v6.

## Reproduction and integrity evidence

[Certain] The completed command was:

```powershell
python tools/swing_cycle_core_suite.py --v7-only --out <temporary-evidence-directory>
```

[Certain] The suite completed 29/29 cases using `BTC-USDT`, `1H`, UTC
2015-01-01 through 2026-01-01 inclusive, 250-day warmup, `$10,000` starting
capital, and next-open fills. The realistic control repeated identically:
`E_v7_cycle_core` and `cost_realistic` both ended at `$13,723,323.31`.

[Certain] Dataset identity was
`ohlcv-v1-c83aa9bc684a` (`c83aa9bc684add63a9d9d88957432b37fd92cd69634612c83e4e6d0e17527c3e`);
the raw cache SHA-256 before and after was
`284b26b68fda8931642a0fd7286a68d806dbf2adcd3d318313a395149d2a073f`.
The audit found 102,931 rows, no gaps, no hard anomalies, and no conflicting
timestamp collisions. The 474 retained identical duplicate timestamps make
comparisons valid only when this dataset identity matches.

[Certain] Closed-bar/causal-fill behavior is covered by
`tests/test_swing_cycle_core.py` and `tests/test_runner_manifest.py`: the
decision uses the prior completed price and the order fills at the following
bar open. The candidate does not consume external macro, funding, or
higher-timeframe inputs.

## Fixed results and falsification

| Case | Cost | Final capital | Max DD | Orders |
|---|---:|---:|---:|---:|
| Buy-and-hold control | realistic | $2.722M | 83.76% | 1 |
| V7 540/900 | realistic | $13.723M | 77.14% | 3 |
| V7 540/900 | conservative | $13.709M | 77.14% | 3 |
| V7 540/900 | twice conservative | $9.778M | 70.33% | 4 |
| 3×3 boundary grid | realistic | $3.212M–$55.855M | 70.49%–83.76% | 1–6 |
| ±120 / ±180-day phase stresses | realistic | $2.722M–$12.089M | 70.34%–83.76% | 1–5 |
| 1/6/12/24/72-hour delays | realistic | $0.634M–$54.396M | 39.05%–77.14% | 2–7 |
| ±365 / ±180-day calendar placebos | realistic | $1.414M–$13.723M | 77.14%–88.51% | 1–3 |

[Certain] The fixed sensitivity and delay checks are adverse evidence: outcomes
vary materially with predeclared phase boundaries and delays. They were not
used to tune the candidate. [Likely] This confirms the anticipated
calendar-rule overfitting risk and means historical results cannot support
adoption; it does not prevent an inactive, isolated forward-paper observation.

## Isolated-paper controls

[Certain] `tools/v7_paper_setup.py` registers two distinct instances,
`swing_cycle_core_v7_btc_usdt_shadow` and
`swing_cycle_core_v7_btc_usdt_paper`, with unique `instance_id`,
`paper_portfolio_id`, and transition-journal paths. Both are inactive unless
an explicit activation flag is supplied and both set `service_managed=True`.

[Certain] Their only permitted execution values are `v7_shadow` and
`v7_local_paper`; `core.v7_operations.assert_paper_only()` rejects a non-paper
settings object or `TRADING_MODE`. The legacy `paper_fleet_setup.py` remains
limited to the v6 simulated/demo control fleet. The dedicated promotion
controller cannot activate V7 paper until its independent shadow-soak gates
pass.

## Next boundary

Human approval is required before running the V7 setup tool, activating shadow
or paper, starting a service, touching the VM, deploying, or promoting any
candidate/default/live behavior.
