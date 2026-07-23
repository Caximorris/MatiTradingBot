# Candidate strategy → isolated paper

This workflow is intentionally shorter than default/live promotion. It establishes that a new,
isolated strategy is safe to observe in paper; it does not establish a trading edge or replace a
frozen default.

## Local engineering gate

1. Write a short hypothesis: mechanism, expected failure, rollback, and finite run budget.
2. Implement a separate `BaseStrategy`, config round-trip, `StrategyMeta`, warmup, closed-bar logic,
   and tests for state transitions, client compatibility, and rollback.
3. Run deterministic paired realistic-cost backtests. Fix code defects, not results, and rerun.
4. Before paper, run conservative costs plus proportionate lookahead and overfitting falsification:
   at minimum an explicit closed-bar/data check and one OOS, rolling-start, or parameter-neighbourhood
   check. Preserve failed variants rather than tuning them away.
5. Run focused tests, full pytest, compileall, build, and Ruff ratchet; inspect the complete diff.

If the code and these checks pass, record `PAPER_CANDIDATE_READY` with the exact config, commands,
data identity, known limitations, and rollback. This label does not imply `ADOPT`.

## Isolated paper gate

Use a candidate-specific setup tool modeled on `tools/v7_paper_setup.py`:

- one unique `instance_id`, `paper_portfolio_id`, wallet, and journal namespace;
- `service_managed=True`, inactive by default, and an execution mode that cannot route to live/demo;
- deactivate-not-delete rollback and append-only evidence.

`tools/paper_fleet_setup.py` is reserved for the v6/demo control fleet. Do not add candidates to
`desired_fleet()`; reconciliation would otherwise contaminate the control or deactivate candidates.

Executing setup, activating paper, a VM pull, or service restart remains an explicit operational
action. Paper evidence can later inform a separate default/live promotion decision.
