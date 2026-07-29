# V8 X-Perp emergency flatten

This procedure is only for the dedicated OKX EEA Demo account and the dynamically
discovered V8 BTC X-Perp. It never authorizes Live operation or mutation of unknown
account state.

## Preconditions

1. Work from the repository root on the intended host.
2. Confirm only the dedicated `OKX_XPERP_DEMO_*` credential triplet is available.
3. Do not use shared or Live credential names.
4. Obtain the exclusive account-scoped process lock by running startup recovery.
5. If any position/order is not proven by the V8 durable ledger, stop. The command
   must return `BLOCKED`; resolve ownership manually in OKX Demo before proceeding.

## Command

```powershell
python tools/v8_xperp_demo.py startup-recovery
python tools/v8_xperp_demo.py flatten --confirm-v8-emergency-flatten
python tools/v8_xperp_demo.py final-reconcile
```

Expected successful output is either `status=flat` or `status=already_flat`, followed
by final position `0` and zero FUTURES open orders. The flatten order, when required,
is persisted before submission and is `reduceOnly=true`.

## Failure branches

- Environment, endpoint, or credential mismatch: do not retry with other credentials.
- Lock conflict: identify the existing V8 process; do not terminate it blindly.
- Corrupt journal/startup recovery failure: preserve the files and stop all automated
  mutation.
- Unknown order or position, multiple positions, or metadata change: do not cancel or
  flatten anything automatically. Verify account ownership manually.
- Ambiguous submission/timeout: use `startup-recovery`; never submit a second blind
  close.
- REST/private-WebSocket disagreement: keep execution blocked. REST reconciliation is
  authoritative only after the durable ledger and full account inventory agree.
- Partial fill or cancel/fill race: re-inventory after cancellation and flatten the
  resulting signed position once, reduce-only.
- A final nonzero position or any open FUTURES order: treat the incident as unresolved
  and escalate to a human operator in OKX Demo.

## Manual account verification

In OKX Demo, verify the selected account, `BTC-USD_UM_XPERP-*`, isolated margin,
net position mode, position quantity zero, and no FUTURES orders. Never infer success
from a WebSocket event alone.

## Evidence

Preserve the sanitized command output, UTC incident start/end, metadata hash, hashed
client ID, pre/post position, cancellation count, terminal state, final full FUTURES
inventory, and startup-recovery result. Do not copy credentials or raw journals into
evidence.
