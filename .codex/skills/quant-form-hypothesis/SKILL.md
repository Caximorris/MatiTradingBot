---
name: quant-form-hypothesis
description: Generate, research, and preregister falsifiable systematic-trading hypotheses. Use for new research ideas, literature reviews, causal mechanism design, experiment questions, kill criteria, or requests to improve a strategy before code or backtests are run.
---

# Quant Hypothesis Design

## Purpose

Convert an intuition into one causal, testable claim with a fixed evidence plan and a reason it
could fail. Reduce idea duplication and post-hoc storytelling before consuming the test set.

## Trigger Conditions

Use for hypothesis generation, literature review, causal mechanism analysis, experiment planning,
or an unstructured request to find an edge or improve a strategy.

## When Not to Use

- Do not implement code, choose parameters from results, or declare an edge validated.
- Do not use for a known hypothesis that only needs execution; use `$quant-run-experiment`.
- Do not reopen an experiment recorded as rejected without new data or a materially different cause.

## Required Context

Read `AGENTS.md`, `SESSION.md`, `EXPERIMENTS.md`,
`../quant-orchestrate-research/references/research-contract.md`, and
`../quant-orchestrate-research/references/project-surface.md`. Inspect the relevant strategy plan and
version history. For literature review, prefer primary papers, official datasets, and exchange
documentation; record links, publication dates, and what is inference rather than sourced fact.

## Workflow

1. Search existing experiments, strategy versions, and plans for duplicates, inert parameters, and
   closed research fronts.
2. State the decision this research should inform and the population/market where it should hold.
3. Write one hypothesis in causal form: because mechanism M affects behavior B, observable X should
   predict or alter outcome Y under conditions C.
4. Define the null, competing explanations, and at least one disconfirming observation.
5. Specify point-in-time inputs, universe, timeframe, sample split, benchmark, cost model, primary
   metric, guardrail metrics, minimum sample, and run budget.
6. Predeclare kill, continue, and success criteria. Prefer ranges/plateaus over a single optimum.
7. Classify the work as exploratory or confirmatory. Reserve an untouched test/forward period.
8. Hand off feature construction to `$quant-research-signals`, implementation to
   `$quant-engineer-strategy`, and execution to `$quant-run-experiment`.

## Verification Steps

- Confirm the idea is not already accepted, rejected, parked, or forbidden in project records.
- Confirm the proposed inputs could have been known at each decision timestamp.
- Confirm the primary metric cannot be silently swapped after observing results.
- Confirm the sample and number of independent events can support the intended claim.
- Confirm the hypothesis can fail without triggering another parameter search.

## Expected Output

Produce a preregistration containing: research ID, question, mechanism, hypothesis, null, competing
explanations, data and availability, benchmark, controls, split, primary/guardrail metrics, costs,
run budget, kill/continue/success gates, artifact plan, primary-source ledger when literature was
used, and required downstream agents/skills.

## Success Criteria

- The hypothesis is singular, causal, falsifiable, and not a disguised parameter sweep.
- A future researcher can execute it without asking what success means.
- Negative evidence will terminate or narrow the idea rather than be tuned away.
