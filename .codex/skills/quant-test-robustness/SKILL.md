---
name: quant-test-robustness
description: Test whether a systematic-trading result generalizes beyond its selected sample. Use for parameter sensitivity, overfitting detection, robustness scoring, regime robustness, stress testing, stability review, walk-forward analysis, Monte Carlo or block-bootstrap validation, rolling starts, execution-delay tests, out-of-sample validation, or parameter optimization with an untouched test set.
---

# Quant Robustness Testing

## Purpose

Try to break a valid backtest across plausible data, parameter, regime, cost, execution, and sampling
perturbations before any claim of generalization or promotion.

## Trigger Conditions

Use for overfitting, sensitivity, stress, walk-forward, OOS, Monte Carlo/bootstrap, rolling windows,
regime stability, robustness scores, or parameter optimization/search.

## When Not to Use

- Do not run until data and backtest integrity are acceptable.
- Do not use the BTC 2015-2026 closed window to select new parameters.
- Do not call a shifted start date or repeated reused window "out-of-sample".
- Do not promote a candidate; hand off to the relevant project-specific gate.

## Required Context

Read `../quant-orchestrate-research/references/research-contract.md`,
`../quant-orchestrate-research/references/project-surface.md`, the preregistration, experiment history,
data verdict, backtest audit, exact baseline, and strategy-specific protocol. Inspect existing
robustness tools before creating a harness; several already cover block bootstrap, rolling starts,
phase sensitivity, stress, costs, and delay.

## Workflow

1. Freeze candidate, baseline, primary metric, guardrails, data split, and run budget before testing.
2. Establish the simplest comparable baseline and a true untouched test/forward period.
3. Map one-at-a-time parameter sensitivity around the candidate. Prefer broad plateaus and monotonic
   mechanisms; penalize isolated optima, cliffs, and inert knobs.
4. Test reasonable joint perturbations only after isolated effects are understood. Record every run.
5. Run fixed-config walk-forward/rolling starts and segment by predeclared regimes/cycles. Report
   independent event counts and concentration.
6. Stress costs, slippage, delay, gaps, extreme price paths, liquidity, funding, and relevant portfolio
   shocks without weakening risk constraints.
7. Use block bootstrap/Monte Carlo that preserves dependence appropriate to the artifact. State what
   is resampled and what cannot be inferred. Never shuffle bars independently.
8. For optimization, use nested validation or train/validation/test separation; select only on inner
   data and evaluate once on untouched outer data. Account for number of trials, selection bias,
   multiple testing, and deflated performance statistics where applicable.
9. Compute a transparent robustness score from preregistered gates; never hide a failed hard gate in
   an average score.

## Verification Steps

- Confirm identical candles/harness/costs within every paired comparison.
- Confirm no test or forward result influenced candidate selection.
- Confirm random procedures have fixed seeds and enough replications; report uncertainty intervals.
- Confirm dependence, regime balance, and trade concentration are visible.
- Confirm all variants and negative results are recorded and no canonical data was altered.

## Expected Output

Produce a robustness matrix covering parameter neighborhoods, windows/starts, regimes, costs,
execution stress, resampling intervals, OOS/forward evidence, concentration, and hard-gate outcomes.
Return `ROBUST`, `FRAGILE`, `INCONCLUSIVE`, or `INVALID_INPUT`, plus the weakest link.

## Success Criteria

- The candidate survives a neighborhood and multiple independent conditions, not one lucky path.
- Optimization and evaluation sets remain separated and the trial count is disclosed.
- The verdict is driven by hard gates and uncertainty, not a composite score alone.
