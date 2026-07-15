---
name: quant-engineer-research-systems
description: Implement and refactor offline quantitative-research infrastructure in MatiTradingBot. Use for backtest engine, client-contract, deterministic data tooling, experiment harnesses, robustness tools, metrics, reports, journal summarizers, profiling, tests, build, or CI changes that do not alter strategy hypotheses or production trading behavior.
---

# Quant Research Systems Engineering

## Purpose

Implement approved research-infrastructure contracts reproducibly while keeping strategy logic,
independent validation, protected evidence, and production operations outside this role.

## Trigger Conditions

Use for changes to `core/backtest.py`, `cli/runner.py`, offline data/research tools, experiment and
reporting harnesses, deterministic artifacts, research performance, tests, build, or CI.

## When Not to Use

- Do not design or tune strategy logic, risk appetite, signals, or promotion criteria.
- Do not certify your own implementation; hand it to independent auditors and code review.
- Do not touch live/demo execution, deploy, canonical caches, journals, DBs, or protected defaults
  without the approvals required by `AGENTS.md`.

## Required Context

Read `AGENTS.md`, `SESSION.md`, the frozen implementation contract, relevant skills' verdicts,
`../quant-orchestrate-research/references/research-contract.md`, target files, consumers, tests,
`pyproject.toml`, command help, and current diff. Inspect existing tools before creating another.

## Workflow

1. Classify the change as data tooling, simulator, execution model, experiment, metrics/reporting,
   performance, test, build, or CI infrastructure.
2. Freeze unchanged behavior, inputs/outputs, acceptance cases, failure behavior, and rollback.
3. Implement the smallest reusable change behind explicit configuration where semantics vary.
4. Preserve `Decimal`, UTC, deterministic ordering/seeds, client compatibility, and artifact identity.
5. Fail closed on invalid experiments; never continue to plausible metrics after integrity errors.
6. Add invariant, boundary, parity, accounting, empty-data, error-path, and determinism tests.
7. Profile before and after performance work; preserve numeric results unless a semantic change was approved.
8. Run focal and repository checks, inspect the complete diff, and record baseline failures honestly.
9. Hand all changes to `$quant-review-code`; add `$quant-validate-data`, `$quant-audit-backtest`, or
   `$quant-model-execution` according to the semantics affected.

## Verification Steps

- Reproduce the original limitation and every acceptance case with evidence.
- Confirm deterministic inputs produce identical timestamp identities, metrics, and artifacts.
- Confirm client signatures and behavior, fee/accounting examples, and failure propagation where relevant.
- Run focal tests, full pytest, compileall, ruff, and build per `AGENTS.md`.
- Review status, full diff, `git diff --check`, file-size limits, secrets, and generated artifacts.

## Expected Output

Produce an implementation contract, files changed, behavior and rollback, tests, commands/results,
performance evidence when relevant, independent validation handoffs, and residual risks.

## Success Criteria

- Research infrastructure is deterministic, testable, maintainable, and fails visibly.
- Strategy semantics and protected evidence remain unchanged unless separately authorized.
- Independent reviewers, not the implementer, issue integrity and engineering verdicts.
