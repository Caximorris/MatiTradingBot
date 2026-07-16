---
name: quant-engineer-strategy
description: Design, implement, refactor, or review systematic-trading strategy domain logic in MatiTradingBot. Use for a new strategy, strategy refactor, entry or exit review, risk-management review, position-sizing review, portfolio/allocation review, or translating an approved hypothesis into reversible code and tests.
---

# Quant Strategy Engineering

## Purpose

Translate a preregistered hypothesis into the smallest reversible domain change while preserving
client compatibility, deterministic backtests, frozen defaults, and an independent validation path.

## Trigger Conditions

Use for new strategy modules, strategy refactoring, or review of entries, exits, risk, sizing,
exposure, portfolio construction, rebalance logic, and strategy configuration.

## When Not to Use

- Do not use for feature discovery, data audits, result interpretation, or robustness verdicts.
- Do not touch frozen Swing defaults or `strategies/pro_trend.py` without explicit approval.
- Do not implement changes to risk limits, sizing, order execution, shorts, or live exchange paths
  without the human approval required by `AGENTS.md`.

## Required Context

Read `../quant-orchestrate-research/references/research-contract.md`,
`../quant-orchestrate-research/references/project-surface.md`, the approved preregistration, relevant
plans, approved signal and `$quant-design-risk` contracts, the target strategy/config,
`strategies/base_strategy.py`, `strategies/registry.py`,
`core/backtest.py`, client-contract tests, direct consumers, and target tests.

## Workflow

1. Classify the request as new isolated strategy, behavior-preserving refactor, or
   strategy-affecting change. Stop at protected/approval boundaries.
2. Define unchanged behavior, changed behavior, approved risk mandate, rollback config, and
   acceptance tests before editing.
3. For a new strategy, implement a `BaseStrategy` subclass and config with `from_dict()`/`to_dict()`,
   register one `StrategyMeta`, declare warmup/output type, and preserve the common client contract.
4. Put new indicators only in `strategies/indicators.py`; document input timestamps and closed-bar
   behavior. Keep interface, persistence, Telegram, and deployment details out of the strategy.
5. Use `Decimal` for money, UTC for persisted timestamps, loguru for logs, and complete
   `OrderResult` fields. Keep paper mode and `allow_shorts=False` defaults unless explicitly approved.
6. Make one hypothesis-driven change at a time behind a default-preserving config switch where
   practical. Never weaken look-ahead or risk controls to obtain passing results.
7. Add unit tests for config roundtrip, gates, entries/exits, state transitions, client compatibility,
   and rollback equivalence. Do not encode desired backtest profits as unit tests.
8. Hand off engineering review to `$quant-review-code` and behavior validation to data, backtest,
   experiment, performance, and robustness skills.

## Verification Steps

- Confirm default behavior and rollback are identical where promised.
- Confirm all clients expose the methods used and tests never place real/demo orders.
- Confirm no current higher-timeframe bar or same-day external context leaks into a decision.
- Run focal tests, full pytest, compileall, lint/build checks required by `AGENTS.md`, and inspect diffs.
- For a refactor, compare deterministic journals/metrics or a stronger behavior-equivalence artifact.

## Expected Output

Produce a change contract, architecture impact, files changed, config/rollback, tests, validation
commands/results, unresolved trading assumptions, approval boundaries, and downstream research gates.

## Success Criteria

- The code is minimal, reversible, client-agnostic, tested, and within repository boundaries.
- Existing defaults and protected strategies remain unchanged unless explicitly authorized.
- Implementation is not misrepresented as evidence that the strategy works.
