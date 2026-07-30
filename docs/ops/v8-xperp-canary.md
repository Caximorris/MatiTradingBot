# V8 capped continuous OKX Demo canary

## Scope and hard boundary

The canary is V8-only, OKX EEA Demo-only, disabled by default, isolated-margin,
net-mode, and capped below `$1,000` actual notional. Live execution and full V8
strategy exposure remain unauthorized.

Hard ceilings/floors:

| Control | Hard value |
|---|---:|
| Actual notional | `$1,000` |
| Active X-Perp instruments / net positions / transition intents | `1 / 1 / 1` |
| Selected leverage | `2x` |
| Daily realized loss | `$25` |
| Total Demo loss | `$100` |
| Minimum liquidation distance | `35%` |
| Spread / estimated slippage | `20 / 15 bps` |
| Market / private-stream age | `5 / 15 seconds` |
| Clock drift | `2 seconds` |
| Consecutive API failures | `3` |
| Unresolved reconciliation | `30 seconds` |
| Expiry warning / new-stop / mandatory-flat | `30 / 14 / 7 days` |

Configuration can reduce these values. A value above a ceiling or below the
liquidation floor is rejected.

## Exact operator commands

Run from the repository root in PowerShell.

```powershell
# Read-only preflight and startup recovery
python tools/v8_xperp_demo.py preflight
python tools/v8_xperp_demo.py startup-recovery

# Canary configuration validation
$env:V8_XPERP_CONTINUOUS_DEMO_ENABLED='true'
python tools/v8_xperp_demo.py canary-config

# One-shot startup gate (opens no position and stops)
python tools/v8_xperp_demo.py canary-start --enable-continuous-demo

# Continuous observer/service; Ctrl+C requests shutdown
python tools/v8_xperp_demo.py run --enable-continuous-demo

# Status and graceful shutdown
python tools/v8_xperp_demo.py canary-status
python tools/v8_xperp_demo.py graceful-shutdown

# Manual stop and emergency flatten
python tools/v8_xperp_demo.py manual-emergency-stop --confirm-v8-emergency-stop
python tools/v8_xperp_demo.py flatten --confirm-v8-emergency-flatten

# Reconciliation and risk status
python tools/v8_xperp_demo.py final-reconcile
python tools/v8_xperp_demo.py funding-status
python tools/v8_xperp_demo.py margin-status
python tools/v8_xperp_demo.py expiry-status
python tools/v8_xperp_demo.py rollover-dry-run

Remove-Item Env:V8_XPERP_CONTINUOUS_DEMO_ENABLED
```

The current service command owns lifecycle, recovery, WebSocket supervision, and the
cap. Strategy target transport is not enabled for unattended operation; the bounded
exercise injects targets directly through the same service boundary.

## Startup runbook

1. Verify dedicated Demo credentials, EEA REST/private-WebSocket allowlists, USDC
   collateral, isolated/net account configuration, system time, and no Live variables.
2. Run preflight, journal validation, startup recovery, configuration validation,
   margin status, expiry status, and funding status.
3. Require flat/zero-order inventory, one current metadata record, 81 valid tiers,
   leverage at most 2x, fresh market/private stream, and no latched loss/manual stop.
4. Run the one-shot startup. Only then may a human start the continuous observer.
5. Keep the `$1,000` cap and do not attach a full-exposure strategy.

## Shutdown runbook

Inject `flat` through the controlled service path, verify the reduce-only terminal
intent, run final reconciliation, then graceful shutdown. If uncertainty or a
nonzero position remains, use the emergency procedure. Confirm no Python executor
process remains.

## Daily reconciliation checklist

- UTC clock drift, endpoint/environment, lock owner, journal/funding/state integrity.
- Full FUTURES position/order inventory and V8 ownership.
- REST/private-stream agreement and ages.
- Instrument metadata, expiry gates, 81-tier continuity, selected leverage, margin,
  liquidation distance, spread, slippage, and available USDC after reserves.
- Daily/total realized losses and exact-once loss IDs.
- Funding expectations due/delayed/missing and consumed bill IDs.
- Maximum observed notional and any kill-switch/incident records.

## Forward-test evidence reports

The executor writes a durable V8 evidence ledger under its isolated runtime root:

- `evidence/events.jsonl`: append-only, fsynced observations, transition events,
  safety failures, unexpected failures, and report creation records.
- `evidence/reports/cycles/cycle-####.json`: one immutable report after each
  completed synthetic four-day cycle.
- `evidence/reports/weeks/YYYY-W##.json`: one immutable report for each completed
  UTC week that has V8 evidence.
- `evidence/delivery.json`: idempotent Telegram delivery receipts. Saved reports
  remain authoritative; an undelivered report is retried after restart.

Each report includes its UTC window, observation/transition/incident counts,
the period events, and the latest reconciled operational state. A report with
missing or corrupt evidence must be treated as incomplete, never as a clean
forward-test period.

## Funding reconciliation runbook

Create one expectation per environment/account/instrument/settlement from a known
position that actually spans settlement. Persist side, contracts, notional, signed
rate, expected signed amount, and source hashes before settlement. Reconcile OKX
type `8`, subtype `173/174`, USDC bills by unique `billId`. If OKX finalizes a
different rate before a bill is matched, rebase the expectation to the official
settlement rate and retain the old-to-new rate revision in the ledger; the actual
bill must still match the rebased amount. Changed bill content, sign, timestamp,
duplicate bills, or a rate change after bill match blocks reconciliation. Amount
differences are accepted only within the bounded 0.1% settlement tolerance after
the official rate, bill identity, sign, and timestamp have passed validation.
At 2 minutes mark delayed; at 15 minutes mark missing. Restarting must reload the
same identity and never consume a bill twice. Report `UNOBSERVED` until an actual
known-position Demo settlement occurs.

## Margin and liquidation runbook

Fetch current metadata, all isolated position tiers, selected leverage, position risk,
and position fields. Select tiers on `abs(contracts) * ctVal`; calculate USD notional
separately. Compare venue `mmr`, margin, mark, leverage, notional, and liquidation price
against the conservative local model. Use the more conservative liquidation price.
Block for missing fields, tier gaps/overlaps, disagreement beyond tolerance, negative
available margin, or distance below 35%. Never deliberately approach liquidation.

## Kill-switch actions

| Action | Reasons |
|---|---|
| Block, stop, manual recovery | environment/Live credential mismatch, lock conflict, corrupt journal, startup failure, API failures, reconciliation timeout, tier failure |
| Block, no mutation, manual recovery | unknown order/position, multiple positions/instruments |
| Block and cancel only known V8 orders | REST/WS disagreement, stale market/stream, spread/slippage, clock drift |
| Cancel known, emergency flatten, stop, manual recovery | liquidation/cap/loss breach, mandatory expiry flat, manual emergency stop |

Unknown state is never modified automatically. Incident recovery requires fresh
startup reconciliation and a human decision before clearing any latch.

## Restart recovery runbook

Do not submit a replacement order. Acquire the account-scoped OS lock, validate the
journal, query by client ID/open orders/history/fills/position, adopt the known
position, and prove accepted-order count did not increase. Reconnect the private
stream, require REST agreement, then resume only from a terminal recovered intent.

## Expiry and rollover runbook

At 30 days warn; at 14 days reject new exposure; at 7 days cancel known pending
orders and require flat. Discover a later live `ruleType=xperp` successor dynamically
and require matching family, underlying, linear contract, value currency/value,
USDC collateral, and a unique earliest later expiry. Compare liquidity, spread,
basis, close/open costs, and quantized BTC-equivalent sizing. A missing/ambiguous
successor returns `BLOCKED`. `rollover-dry-run` has no order client and cannot execute.

## Incident-response checklist

Latch the switch, preserve UTC status and sanitized evidence, inventory the entire
FUTURES account, classify known versus unknown state, cancel only proven V8 orders,
flatten only proven V8 exposure, reconcile REST and private WebSocket, verify flat and
zero orders, stop the process, and obtain manual approval before restart. Follow
`docs/ops/v8-xperp-emergency-flatten.md` for emergency details.

## Canary promotion checklist

Do not increase the cap before at least 30 calendar days, 10 complete controlled
position cycles, 10 observed funding settlements, no unresolved incidents or
reconciliation failures, verified loss accounting, stable margin/liquidation
comparisons, successful restart/reconnect/flatten drills, and independent execution,
risk, robustness, and code review. A human must approve a new cap and rollback plan.

## Demo-to-Live readiness checklist

Live requires a separate explicit authorization and implementation boundary; at least
60 clean Demo days; restricted Live credentials and endpoint attestation; reviewed
fees, funding, margin/liquidation, sizing, and loss budgets; independent security,
execution, risk, and operational reviews; incident/restart/credential-revocation
drills; monitoring and on-call ownership; paired reproducible evidence; and an
approved rollback. None of these gates is waived by historical profitability or this
bounded Demo pass.
