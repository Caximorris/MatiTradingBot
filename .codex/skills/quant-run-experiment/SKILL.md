---
name: quant-run-experiment
description: Execute, compare, and capture reproducible offline quantitative experiments in MatiTradingBot. Use for running backtests, fixed candidate comparisons, experiment automation, controlled ablations, stress matrices, journal generation, or coordinating a frozen preregistered run matrix. Use `quant-curate-evidence` for final ledgers and research reports.
---

# Quant Experiment Runner

## Purpose

Execute a preregistered experiment through the repository's existing harnesses, preserve every run,
and produce comparable evidence without making the methodological verdict for specialist gates.

## Trigger Conditions

Use for backtest execution, strategy/candidate comparisons, ablations, fixed run matrices, journal
summaries, experiment registry updates, and HTML/Markdown report generation.

## When Not to Use

- Do not generate hypotheses after seeing results, waive data/backtest gates, or optimize adaptively.
- Do not run paper/live commands, demo smoke tools, Telegram sends, deployment, or remote actions.
- Do not write `EXPERIMENTS.md` unless the request changes documented project research state and the
  evidence/decision is complete.

## Required Context

Read `../quant-orchestrate-research/references/research-contract.md`,
`../quant-orchestrate-research/references/project-surface.md`, the preregistration,
strategy-specific protocol, and `references/experiment-record.md`. Inspect command help and tool
source before execution. For Swing, invoke `$mati-swing-validator` and use its exact paired harness.

## Workflow

1. Freeze the experiment ID, candidate/baseline configs, symbol/timeframe, UTC windows, warmup,
   dataset identity, costs, seed, run budget, primary metric, guardrails, and stop rules.
2. Validate data and backtest integrity or record existing valid verdicts.
3. Prefer `cli/runner.py`-based commands and existing tools. Never mix CLI and specialized-harness
   numbers in one paired comparison.
4. Fetch/slice once and reuse identical bars when the harness supports it. Run at most five
   backtests in parallel and keep deterministic seeds.
5. Capture command, resolved config, code revision/status, candle count, start/end, cost mode,
   runtime, metrics, warnings, and artifact path for every run, including failures.
6. Summarize journals with `tools/journal_summary.py`; never load raw large JSON journals.
7. Compare candidate and baseline metric-by-metric. Report effect sizes and guardrail failures; do
   not collapse conflicting metrics into "better".
8. Generate raw/factual artifacts through existing tools when requested and safe; hand final report
   assembly and ledger updates to `$quant-curate-evidence`.
9. Hand descriptive analysis to `$quant-analyze-performance` and generalization to
   `$quant-test-robustness` before a final research verdict.
10. Do not update project decision docs; provide the complete manifest to `$quant-curate-evidence`.

## Verification Steps

- Confirm every paired run has identical candle timestamps, window, warmup, cost mode, harness, and
  output semantics.
- Confirm requested run count stayed within the preregistered budget and failures remain visible.
- Confirm repeat runs on cached data are deterministic.
- Confirm generated reports reference the exact artifacts and resolved config.
- Review git status/diff for accidental journals, caches, DBs, logs, secrets, or runtime artifacts.

## Expected Output

Produce an experiment manifest, command log, run table, paired comparison, failure/warning log,
artifact index, and handoff status for performance, robustness, and evidence curation. Use the
record schema in the bundled reference.

## Success Criteria

- Another researcher can reproduce each run exactly.
- Candidate and baseline comparisons are genuinely paired.
- The complete search path and negative results are preserved.
- No live/external mutation or unapproved strategy change occurs.
