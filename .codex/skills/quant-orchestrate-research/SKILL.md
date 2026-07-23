---
name: quant-orchestrate-research
description: Orchestrate end-to-end systematic-trading research in MatiTradingBot. Use for broad or ambiguous requests such as "research a new idea", "improve this strategy", "find overfitting", "compare indicators", "validate robustness", or "optimize parameters" when Codex must select and sequence multiple quantitative research skills without changing frozen trading logic by default.
---

# Quant Research Orchestrator

## Purpose

Route a research request through the minimum independent custom agents needed to produce a
reproducible, falsifiable conclusion. The root agent is the dispatcher; do not substitute
orchestration prose for specialist work.

## Trigger Conditions

Use this skill only when the user asks for broad research, an independent audit, or a
promotion/default decision. It is not the default path for implementing an isolated strategy.

## When Not to Use

- Do not use for a normal strategy implementation, repair, backtest iteration, or paper-candidate
  preparation; use `$quant-engineer-strategy` and the candidate-paper workflow instead.
- Do not use for paper/live operations, deployment, or exchange actions.
- Do not use as authority to change a frozen default or promote a candidate.

## Required Context

Read `AGENTS.md`, `SESSION.md`, and these references before acting:

- `references/research-contract.md` for global evidence and safety gates.
- `references/project-surface.md` for the real repository capabilities.
- `references/skill-map.md` for routing and handoffs.

If the request involves Swing Allocator, also invoke `$mati-swing-validator` and follow its stricter
promotion protocol.

## Workflow

1. Restate the decision to be made, not merely the requested activity.
2. Classify the work as hypothesis, signal, strategy, data, backtest, robustness, performance,
   execution, risk, experiment, evidence, or engineering. Select only the required custom agents
   from the map.
3. Inspect existing experiments and discarded ideas before proposing work. Do not reopen a closed
   path without new evidence.
4. Establish only the evidence chain needed for the decision. A candidate-paper decision may use
   local implementation and its defined validation suite; promotion needs the full applicable chain.
5. Spawn only specialists with a distinct unanswered question. Never create agents merely to satisfy
   process, duplicate an existing test, or obtain a receipt.
6. Separate implementation from validation. An implementing agent cannot validate or waive an
   independent data, execution, bias, risk, code-review, or robustness gate.
7. Default "optimize parameters" to sensitivity mapping and falsification. Require a run budget and
   an untouched test set before using results for a default/promotion decision.
8. Stop at any approval boundary or integrity failure. Preserve negative and inconclusive results.
9. Send completed artifacts to `evidence-curator`; return one integrated memo without overriding
   any specialist verdict.

## Verification Steps

- Confirm every claim maps to an inspected file, command output, journal summary, or cited source.
- Confirm paired runs use identical windows, candles, costs, warmup, configuration path, and harness.
- Confirm no protected file, canonical cache, journal, runtime DB, or external system was mutated.
- Confirm selected specialists answered the question they were assigned; do not manufacture gates.
- Confirm no two writer agents edited concurrently.
- Review `git status`, the full diff, and generated artifacts before declaring completion.

## Expected Output

Produce:

1. Decision and scope.
2. Selected custom-agent and skill sequence with the reason for each gate.
3. Preregistered hypothesis and falsification criteria, when applicable.
4. Evidence table with dataset, window, costs, candle count, configuration, metrics, and artifacts.
5. Findings split into observed facts, inferences, and uncertainty.
6. Verdict: `SUPPORTED`, `REJECTED`, `INCONCLUSIVE`, or `BLOCKED`.
7. Remaining risks and the cheapest decisive next experiment.

## Success Criteria

- The request is routed without overlapping ownership or missing a material integrity gate.
- The conclusion is reproducible from named commands and artifacts.
- A negative result is retained rather than tuned away.
- No trading default changes and no live action occurs without explicit authorization and the
  project-specific promotion protocol.
