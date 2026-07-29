Objective: Implement dynamic mid-phase V8 bootstrap and unattended target transport, prepare secure systemd/deployment assets, validate, commit, push, and hand the user exact VM commands. The user will pull and execute remotely. Live remains prohibited.

Classification: strategy-affecting operational startup policy plus local deployment preparation. Frozen V8 historical backtests and V7 remain unchanged.

Authorization:
- Push committed V8 work is authorized.
- The user explicitly withdrew authorization for Codex to perform VM/SSH/systemd/order actions; Codex must only prepare commands for the user.
- Live orders, Live endpoints/credentials, V7 mutation, full exposure, and canary cap above $1,000 remain unauthorized.

Frozen inputs:
- Recovery checkpoint `12501d0`.
- Canary implementation `bc6b97a`.
- Confirmed halving timestamps from `strategies/cycle_phase_clock.py`.
- Scheduled V8 transitions: halving +540 short 2x, +900 long 2x.
- Bootstrap defaults: 20% equity-loss budget, 2x maximum, 0.25x minimum entry.

Change contract:
- A known position on restart is adopted without resize/rebootstrap.
- A flat account exactly at a scheduled transition uses the scheduled 2x target subject to safety/cap.
- A flat account mid-phase computes one deterministic same-source BTC-USD-index bootstrap decision and freezes it.
- Missing/inconsistent causal reference data, ambiguous phase, or leverage below minimum remains flat.
- No unchanged target is resubmitted. Scheduled transitions may replace bootstrap; process restart may not.
- Rollback: stop/disable the V8 unit and return to committed `bc6b97a`; preserve runtime evidence/state.

Diagnostic contract:
- Compare a finite, preregistered set of historical cold starts against flat-until-transition, fixed 1x, and immediate 2x.
- Use frozen 20%/0.25x parameters without optimization; diagnostic results do not replace historical V8 artifacts.

Milestones:
1. [complete] Inspect scheduler, halving/index data, deployment path, and remote branch state.
2. [complete] Implement/test bootstrap calculation and frozen decision ledger.
3. [complete] Implement/test scheduled/bootstrap/restart target transport and monitoring.
4. [complete] Add diagnostic runner, secure systemd/deployment assets, and operator runbook.
5. [complete] Run all local validation and exact V7 replay.
6. [in progress] Commit dynamic bootstrap separately and push exact committed V8 state.
7. [pending] Deliver exact VM pull/config/install/preflight/activation/restart/monitoring commands.

Safety state at milestone start:
- Local Demo account was authenticated flat with zero FUTURES open orders.
- No local Python executor was running.
- Continuous Demo was stopped.
- Remote branch did not yet contain `bc6b97a`.

Latest no-order evidence:
- Authenticated local preactivation passed with `execute=false`; account was flat.
- Phase: short, day-540 transition 2025-10-12T00:09:27Z.
- Same-source reference: BTC-USD index open 109765.4 at 2025-10-12T01:00:00Z.
- Current index at calculation: 64263.5; adverse move 0.7080520046371579512475977810.
- Dynamic leverage 0.2824651278298268863498007776; canary result short 0.0155 contracts,
  996.8515 USD estimated notional, actual leverage 0.009969866810660179748723525866.
- No bootstrap/target intent was persisted and no order was submitted.

Next action:
- Inspect the scoped staged diff, commit, and push. Do not connect to the VM.
