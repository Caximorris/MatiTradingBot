# Swing Allocator v7 Cycle Core — plan

## Decision and scope

This document specifies an isolated, paper/shadow-only research candidate.  It does
not alter Swing Allocator v6-2, its defaults, its phase router, its funding overlay,
or its operational instances.

The candidate hypothesis is deliberately simple: hold 100% BTC in `post_halving`,
`bull_peak`, and `accumulation`, and hold 0% BTC in `bear_onset`.  It has no technical
signals, overlays, leverage, shorting, or discretionary rebalance logic.

## Evidence status

`ARCHIVAL_NON_REPRODUCIBLE_REFERENCE` is the documented v6-2 headline result of
$9,505,067.92.  It cannot be recertified because the exact Bybit funding snapshot
and experiment manifest are unavailable.  It is not an executable baseline.

The current reproducible comparison baseline is `V6_CURRENT_INPUTS_CONTROL`: frozen
v6-2 code run serially against the current canonical BTC cache and the locally
identified funding snapshot.  It must never be described as reproducing the archival
reference.

The canonical cache is immutable for this work.  Its raw SHA-256, ordered semantic
fingerprint, row counts, duplicate count, slicing semantics, resolved configurations,
costs, environment, and run manifests are captured before execution.  Duplicate rows
are retained.  The 102,930/102,931 discrepancy is reported as inclusive-end slicing
or observation-count semantics unless the frozen-input diagnostic proves otherwise.

## Architecture

`strategies/swing_cycle_core.py` is a separate registered strategy.  It owns an
immutable UTC `CyclePhaseClock`, confirmed historical halving calendar, fixed bounds,
and a separate persistent namespace.  It must not import or call
`macro_context.set_phase_bounds()` and cannot consume research-only boundary settings.

Its transition state is persisted as one of `STABLE_RISK_ON`, `EXIT_PENDING`,
`EXIT_ORDER_SUBMITTED`, `BEAR_CASH`, `ENTRY_PENDING`, `ENTRY_ORDER_SUBMITTED`, or
`ERROR_LOCKED`.  Phase changes bypass ordinary threshold and cooldown rules.  Stable
phases only reconcile a documented execution residual.  Unknown phase, bad state,
stale/anomalous market data, or inconsistent phase data holds existing exposure and
locks unsafe retries; no fallback target is allowed.

V7 evaluates only at UTC four-hour boundaries.  The decision uses the closed bar at
that timestamp; the engine's fill timing is recorded in the manifest.  Restarted
paper/shadow/live instances load the same state and transition identity, while
backtest and paper/shadow use the same decision function.  Legacy v6 bar-count cadence
is preserved.  When cadence differs, reports distinguish `V6_LEGACY_CURRENT_INPUTS`
from an explicitly configured `V6_SHARED_CADENCE_CURRENT_INPUTS` control.

## Frozen experiment protocol

All cases use the same ordered bars, inclusive range semantics, starting balance,
cost mode, metric definitions, and recorded execution contract.  They are resumable
only when their manifest identity validates.

Required variants are: A) BTC buy-and-hold, B) frozen v6 current inputs, C) v6 with
only EMA50 cap disabled, D) bull-phase hold preserving v6 bear/accumulation policy,
E) v7 100/100/0/100, and F) v7 100/100/20/100.  No selection is allowed from the
variants.

The fixed robustness work is the 3x3 480/540/600 by 840/900/960 grid; +/-120-day
paired shifts; +/-180-day bear-duration tests; realistic, conservative, and twice
conservative costs; 1/6/12/24/72-hour transition delay; and -365/-180/+180/+365-day
halving-calendar placebos.  Each case records status, runtime, retry count, metrics,
manifest identity, and failure details atomically.

Phase attribution normalizes both candidate and BTC equity to 1.0 at each contiguous
phase segment.  Cycle reporting treats the pre-2016 period as partial, 2016-20 and
2020-24 as the only complete observations, and 2024-current as incomplete.  CSCV/PBO
and Deflated Sharpe are not decision statistics here because two completed cycles are
not an adequate independent sample.

## Acceptance and verdict

The candidate fails if it changes v6, mutates the cache, leaks future data, lacks
manifest identity, violates phase/state idempotency, generates stable-phase tactical
orders, or cannot reproduce decisions across adapters for an identical snapshot.

Historical results are exploratory, not out-of-sample.  `ADOPT` is unavailable without
independent forward evidence and explicit approval.  The allowed historical outcome is
`REJECT` or `NEEDS_MORE_VALIDATION`, with all negative evidence retained.
