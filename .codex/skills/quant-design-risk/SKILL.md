---
name: quant-design-risk
description: Design and independently review portfolio risk, exposure, drawdown constraints, position sizing, loss budgets, allocation limits, and capital-preservation rules for systematic trading. Use for risk-budget design, sizing review, portfolio concentration, allocator exposure, stop-distance sizing, risk-of-ruin, prop-rule constraints, or any proposed change to `core/risk_manager.py` or strategy risk controls.
---

# Quant Portfolio Risk Design

## Purpose

Define risk constraints independently from alpha design and performance interpretation. Convert risk
tolerance into testable portfolio limits without using improved backtest returns as the justification.

## Trigger Conditions

Use for portfolio and position risk budgets, exposure caps/floors, stop-based sizing, drawdown limits,
loss streaks, risk of ruin, concentration, allocator inventory, or review of risk-control proposals.

## When Not to Use

- Do not invent signals, tune entries/exits, interpret general performance, or approve a strategy.
- Do not implement risk, sizing, order, short, or frozen-default changes without explicit approval.
- Do not weaken a hard limit because it reduces CAGR or causes an experiment to fail.

## Required Context

Read `AGENTS.md`, `SESSION.md`, the preregistration, integrity verdicts, and
`../quant-orchestrate-research/references/research-contract.md`. Inspect `core/risk_manager.py`,
`config/settings.py`, strategy-specific sizing/allocation code, `core/prop_rules.py` when relevant,
and existing risk tests. For Swing, also invoke `$mati-swing-validator`.

## Workflow

1. Define the capital base, horizon, instrument, leverage, liquidity, and loss tolerance.
2. Separate sizing intent from notional exposure, stop loss, margin, and realized-loss accounting.
3. Inventory portfolio, symbol, position, daily-loss, drawdown, concentration, and operational limits.
4. Model ordinary, stressed, correlated, gap, depeg, funding, and unavailable-liquidity scenarios.
5. Estimate risk of ruin and breach probability with dependence-aware assumptions and uncertainty.
6. Propose the smallest transparent constraint set, with units, precedence, failure behavior, and rollback.
7. Specify tests before implementation; hand approved code work to `$quant-engineer-strategy` or
   `$quant-engineer-research-systems` according to ownership.
8. Require independent performance and robustness review after implementation.

## Verification Steps

- Reconcile every percentage to its correct capital denominator and UTC measurement window.
- Test boundary values, simultaneous positions, gaps through stops, partial exits, and stale balances.
- Confirm `Decimal` use for money and distinguish quantity, notional, equity, margin, and risk amount.
- Confirm paper/backtest/live clients enforce equivalent intent where applicable.
- Confirm no protected limit or default changed without approval and rollback.

## Expected Output

Produce a risk mandate with capital base, risk budget, exposure and concentration limits, sizing
formula, loss/drawdown gates, stress scenarios, breach probabilities, assumptions, implementation
contract, tests, rollback, and verdict `ACCEPTABLE`, `OVEREXPOSED`, `UNDERDEFINED`, or `BLOCKED`.

## Success Criteria

- Risk limits are explicit, independently justified, testable, and not optimized for returns.
- Strategy engineering receives an unambiguous risk contract rather than discretion to choose limits.
- Approval boundaries and failure-safe behavior remain visible.
