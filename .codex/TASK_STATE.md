Objective: Add an isolated accelerated V8 synthetic Demo cycle and a V8-only Telegram operator interface, update deployment assets, validate, commit, and push. Do not access the VM, start services, mutate Telegram externally, or place Demo/Live orders.

Classification: Strategy-affecting scheduler/target-ownership change plus execution-control interface and deployment preparation. Real-cycle behavior remains the default; V7 is a historical regression control.

Authorization:
- Local implementation, validation, commit, and push of the current branch are authorized.
- VM/SSH/systemd actions, service start/stop, external Telegram mutation, and all Demo/Live orders are prohibited.
- Live execution remains disabled. The existing USD 1,000 Demo canary cap may not be raised.

Change contract:
- Schedule modes are `real_cycle` (default) and `synthetic_demo_cycle`.
- Synthetic mode is possible only for OKX Demo, dedicated X-Perp Demo credentials, Live disabled, an explicit enable flag, and a valid UTC anchor.
- Synthetic Day 0/4 is long 2x, Day 2 is short 2x, Day 3 is long 2x; exact UTC/server time and deterministic isolated IDs/state are required.
- Restart adopts persisted synthetic state/position without duplicate transitions or exposure recalculation.
- Mode switches fail closed unless stopped, reconciled, flat, order-free, intent-free, acknowledged, archived, persisted, and recovered.
- Telegram is V8-only, allowlisted, audited, confirmation-gated for mutations, executor-authoritative, degraded read-only when unhealthy, and unable to weaken Live/environment/canary/reconciliation/schedule controls.
- Rollback: stop the V8 service, flatten through the reviewed path if needed, restore `real_cycle`, archive synthetic state, and revert this scoped commit; preserve runtime evidence.

Milestones:
1. [complete] Inspect current V8 scheduler/service/persistence/Telegram/deployment code, direct consumers, tests, and protected execution contracts.
2. [complete] Implement isolated schedule modes, synthetic cycle state/preview/switching, and focused tests.
3. [complete] Implement V8-only Telegram authorization, reporting, confirmations, reliability, executor routing, and focused tests.
4. [complete] Update environment/systemd/runbook assets without deploying or starting services.
5. [complete] Run focused V8/Telegram tests, full suite, compile, build, Ruff changed files/ratchet, diff checks, and exact V7 replay.
6. [complete] Review final diff/status, commit only scoped changes, push current branch, and report operator commands.

Prior checkpoint:
- Existing dynamic-bootstrap/intent-recovery work is pushed through commit `423104c` on `origin/codex/v8-xperp-intent-recovery`.

Evidence:
- Initial branch/status: `codex/v8-xperp-intent-recovery` tracking its origin; clean worktree before this task-state update.
- Final full repository suite: 700 passed, 10 dependency deprecation warnings.
- Final compileall and build: passed.
- Changed-file Ruff: passed.
- Ruff ratchet: passed, 202 remaining versus 209 baseline.
- `git diff --check`: passed (line-ending conversion warnings only).
- Exact frozen V7 normalized replay (`98fb5ca` harness): final capital
  `54002022.18728089349690`, 6 orders. A generic non-normalized suite case produced a different
  3-order result and was rejected as the wrong replay contract; its temporary worktree/output were
  removed.

Next action:
- Human operator reviews the pushed commit and follows the V8 VM runbook; Codex performs no VM,
  service, Telegram, Demo-order, or Live-order action.
