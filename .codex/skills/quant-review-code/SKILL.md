---
name: quant-review-code
description: Review quantitative-research code and tooling for engineering quality. Use for code review, architecture review, performance profiling, memory optimization, dependency review, test generation, CI review, determinism, reproducibility, maintainability, or repository-boundary analysis without judging trading edge.
---

# Quant Code Review

## Purpose

Evaluate whether the research platform is correct, maintainable, deterministic, efficient, and safe
without substituting software quality for statistical validity.

## Trigger Conditions

Use for code/architecture reviews, profiling, memory optimization, dependency audits, test design,
CI/build review, reproducibility, concurrency, or maintainability of research tooling.

## When Not to Use

- Do not judge signal economics, strategy robustness, or metric attractiveness.
- Do not refactor frozen strategy paths merely for style during forward test.
- Do not add dependencies or change CI/deploy/permissions without required approval.

## Required Context

Read `AGENTS.md`, `SESSION.md`,
`../quant-orchestrate-research/references/research-contract.md`,
`../quant-orchestrate-research/references/project-surface.md`, target files, direct consumers,
relevant tests, `pyproject.toml`, and current git diff. Respect the existing baseline:
pytest/compile/lint/build failures must be remeasured and not attributed without causal evidence.

## Workflow

1. Define review scope and rank correctness, determinism, safety, maintainability, performance, and
   operability risks separately.
2. Trace architecture boundaries and dependency direction: interface -> core/application ->
   strategies/adapters; keep infrastructure and secrets outside domain code.
3. Review errors, validation, timeouts, resource cleanup, logging, Decimal/UTC handling, state
   transitions, concurrency, and external side effects.
4. Review research reproducibility: config serialization, seeds, cache identity, environment capture,
   artifact naming, stable ordering, and deterministic tests.
5. Profile before optimizing. Measure wall time, CPU, allocations, peak memory, I/O, and hot paths on
   representative offline workloads. Preserve numeric behavior when optimizing.
6. Review dependencies for necessity, maintenance, licensing/security, duplication, and compliance
   with `aiohttp`/`urllib.request` instead of `requests`.
7. Generate tests at invariant and boundary seams: client contract, config roundtrip, timestamp edges,
   accounting, empty data, network failure, idempotency, and rollback. Avoid tests that bless profits.
8. Review CI/build configuration against canonical commands; never hide lint, security, or test debt.
9. Report actionable findings first. Hand research-infrastructure fixes to
   `$quant-engineer-research-systems` and strategy fixes to `$quant-engineer-strategy`; preserve an
   independent reviewer for the resulting change.

## Verification Steps

- Reproduce each finding or cite a tight file/line path and failing invariant.
- Run focal tests, full pytest, compileall, ruff, and build when code changes; distinguish baseline debt.
- Re-run profiles under comparable conditions and report variance, not a single timing.
- Inspect `git diff --check`, full diff, status, secrets/runtime artifacts, and file-size limits.
- Confirm behavior-preserving work does not change deterministic backtest outputs where relevant.

## Expected Output

Produce findings ordered by severity with file/line, evidence, impact, remediation, and scope boundary;
then architecture summary, profile table when relevant, test gaps, dependency/CI status, validation
commands/results, and residual risks.

## Success Criteria

- Every finding is reproducible and separates engineering risk from trading risk.
- Optimizations are measured and preserve numeric/research behavior.
- Tests target invariants and failure modes rather than expected profitability.
