---
name: quant-curate-evidence
description: Curate, validate, index, compare, and communicate quantitative-research evidence in MatiTradingBot. Use for experiment ledgers, artifact manifests, journal/report schema checks, result provenance, evidence tables, negative-result preservation, comparison packs, or assembling a final research report from completed specialist verdicts.
---

# Quant Research Evidence Curation

## Purpose

Turn completed research artifacts into an auditable evidence package without running new searches,
changing results, or substituting polished reporting for missing validation.

## Trigger Conditions

Use for experiment records, artifact indexes, journal/report validation, evidence-linked comparisons,
decision-history updates, research memos, and final report assembly.

## When Not to Use

- Do not invent hypotheses, execute adaptive experiments, calculate new edge, or issue integrity,
  performance, robustness, risk, or promotion verdicts.
- Do not rewrite historical records or omit negative, failed, or inconclusive runs.
- Do not read raw large journals; use `tools/journal_summary.py`.

## Required Context

Read `AGENTS.md`, `SESSION.md`, `../quant-orchestrate-research/references/research-contract.md`,
the preregistration, experiment manifest, all required specialist outputs, and
`../quant-run-experiment/references/experiment-record.md`. Inspect existing report and summary tools
before creating another format.

## Workflow

1. Inventory every run, command, resolved config, revision/tree state, dataset identity, seed, cost
   model, warning, failure, metric table, specialist verdict, and artifact.
2. Validate artifact existence, schema, internal identifiers, timestamps, hashes when available,
   and consistency with the manifest.
3. Reconcile factual comparisons without selecting metrics after the result.
4. Keep observed facts, specialist interpretations, and unresolved uncertainty in separate sections.
5. Preserve rejected variants, invalid runs, missing gates, and contradictory evidence.
6. Assemble a report with direct artifact paths and named reproduction commands.
7. Update `EXPERIMENTS.md`, version records, or plans only when a completed decision changes state;
   append evidence and rollback without rewriting history.
8. Return incomplete packages to the owning specialist rather than filling gaps with prose.

## Verification Steps

- Confirm every headline number maps to one exact run and consistent units/definitions.
- Confirm baseline and candidate share window, timestamps, costs, warmup, harness, and output semantics.
- Confirm all required data, backtest, execution, performance, risk, and robustness verdicts are present.
- Confirm links/paths, commands, dates, and decision status against the repository.
- Review status/diff and exclude secrets, DBs, caches, raw journals, logs, and generated noise.

## Expected Output

Produce an evidence index, provenance table, validated comparison, specialist-verdict matrix,
limitations/failures ledger, decision history, reproduction commands, and final research memo. Mark
the package `COMPLETE`, `COMPLETE_WITH_LIMITATIONS`, or `INCOMPLETE`.

## Success Criteria

- A reviewer can trace every claim to a named artifact and reproduce the evidence chain.
- Negative and invalid results remain visible.
- Reporting never overrides a failed gate or manufactures certainty.
