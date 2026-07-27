# V7 Cycle Core — isolated paper readiness

## Current record

V7 is a `CERTIFIED_CAUSAL_CANDIDATE`, not an adopted default. The authoritative
historical reference is the normalized, timestamp-based next-open replay documented
in [`../SWING_V7_CYCLE_CORE_RESULTS.md`](../SWING_V7_CYCLE_CORE_RESULTS.md):
$54,002,022.18728089349690 from $10,000, six fee-reserved operations, and
certified/reference reconciliation `PASS`.

## Frozen candidate contract

- 100% BTC in post-halving, bull-peak, and accumulation; 0% BTC in bear-onset.
- Confirmed halving clock, UTC four-hour completed-bar decisions, and next-1H-open fills.
- Unleveraged, no shorts, no external macro/funding/higher-timeframe inputs, and no tactical
  stable-phase orders.
- Exact duplicate candles are collapsed; conflicting or unordered candles fail closed.
- Rollback is deactivation of the isolated candidate while preserving its wallet, transition
  journal, and evidence.

## Activation boundary

`tools/v7_paper_setup.py` registers separate shadow and local-paper instances, inactive by
default. Running setup, activation, VM/deployment work, Demo-account ownership, default
promotion, and any live action each require explicit approval.
