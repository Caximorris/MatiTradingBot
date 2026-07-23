# Current operational state — 2026-07-23

Read this index, not historical journals. Historical detail is in `docs/archive/session-archive.md` and
strategy-specific plans.

## Active controls

- **Frozen default:** Swing Allocator v6-2. Do not alter its defaults without explicit approval.
  v5 remains the rollback/control. Details and forward evidence: `docs/swing/v6-plan.md` and
  `docs/forward-test/contract.md`.
- **Pro Trend:** frozen/paused; do not tune its parameters.
- **Paper fleet:** v6 simulated + v6 OKX Demo only. Prop is retired. `tools/paper_fleet_setup.py`
  reconciles this control fleet and must never register a research candidate.
- **Candidate V7:** source preserved on branch `codex/v7-paper-operations` in commit `739b202`.
  Its paper path is isolated and remains inactive until an explicitly approved setup/activation.
- **Live:** not authorized. Any VM, bot start/stop, demo/live order, Telegram mutation, or deployment
  requires explicit current-task approval.

## Research facts that remain relevant

- Canonical BTC 1H cache has 102,931 rows and 474 known identical duplicate timestamps. Do not mutate it.
- Current local host uses Python 3.14; use 3.12/3.13 or CI for supported package checks when available.
- Swing v6-2's protected historical anchors require the exact cached funding input; do not re-certify or
  promote from a different input. Funding freshness must be valid before accumulation.
- Closed historical samples may measure robustness but do not by themselves justify a new default.

## Next operating path

For a new strategy, use `docs/forward-test/candidate-paper-workflow.md`: implement, backtest, fix,
falsify for lookahead/overfitting, validate, then label it `PAPER_CANDIDATE_READY`. Separate setup and
paper activation require user approval; default/live promotion is a later independent decision.

## References

- General architecture/commands: `AGENTS.md`.
- Existing experiment and version records: `EXPERIMENTS.md`, `backtests/STRATEGY_VERSIONS.md`.
- V7 details: `docs/SWING_V7_CYCLE_CORE_PLAN.md`, `tools/v7_paper_setup.py`,
  `tools/v7_promotion_controller.py`.
- Deployment controls: `docs/ops/deploy-paper.md`.
