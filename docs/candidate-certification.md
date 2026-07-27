# Universal candidate certification gate

`python main.py certify-candidate --strategy <strategy>` is the only entrypoint
that may label a new candidate result valid or make it eligible for shadow/paper
registration. A historical `backtest`, report, or journal is archival evidence and
is never a certification result.

Every new candidate must implement a `certified_factory` in `StrategyMeta` whose
strategy receives only `StrategySnapshot` and returns `TargetIntent`. The snapshot
contains completed bars only and external events published no later than the decision
time. The engine alone chooses the next-open fill and reserves fees/slippage before
accepting size. A missing adapter is `INVALID`, persists a record, and blocks headline
reporting and shadow/paper registration.

The old V7 `$47.863M` table is historical non-certified evidence. It must be treated
as `INVALID_NON_CAUSAL` until V7 has a certified adapter and reproducible manifest.
Frozen V6-2 and canonical data are not migrated or modified by this gate.

## Current certified report

The current causal manifests are `VALID`:

- V7 Cycle Core: final capital `$52,236,346.57893721564825`, six reconciled
  target intents, with fixed-seed moving and stationary block-bootstrap evidence.
- Adaptive Trend: final capital `$639,663.07877812816615`, 4,049 reconciled target
  intents, with the same fixed-seed bootstrap methods.

V7's `$47.863M` outcome is `INVALID_NON_CAUSAL`, and its `$13.723M` stopped path is
`INVALID_INCOMPLETE_EXECUTION_PATH`. Certification does not alter frozen V6-2,
canonical data, paper activation, or live authorization.
