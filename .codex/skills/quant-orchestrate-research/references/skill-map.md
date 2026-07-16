# Quant Agent and Skill Map

The root agent applies `$quant-orchestrate-research` and spawns the named custom agents directly.
Default subagent depth is one; do not rely on a spawned orchestrator to create grandchildren.

| Intent | Custom agent | Primary skill | Required handoffs |
|---|---|---|---|
| Research a new idea or literature | `hypothesis-researcher` | `$quant-form-hypothesis` | signal/data/experiment as specified |
| Compare indicators, regimes, or market structure | `signal-researcher` | `$quant-research-signals` | data -> experiment -> performance |
| Implement or refactor strategy behavior | `strategy-engineer` | `$quant-engineer-strategy` | code review -> data/backtest gates |
| Design sizing, exposure, or risk limits | `portfolio-risk-specialist` | `$quant-design-risk` | implementation -> performance/robustness |
| Validate a dataset or time alignment | `data-integrity-auditor` | `$quant-validate-data` | backtest audit if results exist |
| Specify fees, slippage, funding, or fills | `execution-model-specialist` | `$quant-model-execution` | systems implementation -> backtest audit |
| Find look-ahead, leakage, bias, or accounting errors | `backtest-integrity-auditor` | `$quant-audit-backtest` | data/execution verdicts first |
| Implement research/backtest infrastructure | `research-systems-engineer` | `$quant-engineer-research-systems` | independent code/data/backtest review |
| Find overfitting or optimize parameters | `robustness-statistician` | `$quant-test-robustness` | hypothesis -> experiment; untouched OOS required |
| Analyze equity, DD, trades, exposure, and metrics | `performance-analyst` | `$quant-analyze-performance` | risk/robustness for prescriptive claims |
| Execute a fixed run matrix | `experiment-operator` | `$quant-run-experiment` | required integrity gates before execution |
| Curate provenance, journals, comparisons, and reports | `evidence-curator` | `$quant-curate-evidence` | all required specialist verdicts |
| Review architecture, performance, deps, tests, or CI | `independent-code-reviewer` | `$quant-review-code` | semantic auditors as applicable |
| Validate or promote Swing Allocator | `swing-domain-validator` | `$mati-swing-validator` | all relevant generic gates plus Swing protocol |

## Standard sequences

- New idea: hypothesis -> signal -> data -> strategy/risk implementation -> code review ->
  execution/backtest audit -> experiment -> performance -> robustness -> evidence.
- Existing backtest: data -> execution contract -> backtest audit -> performance -> robustness -> evidence.
- Strategy change: hypothesis -> signal/risk contracts -> strategy engineering -> code review -> data
  and execution -> backtest audit -> experiment -> robustness -> domain gate.
- Parameter optimization: hypothesis -> data split and budget -> experiment -> nested/untouched OOS
  -> sensitivity plateau -> robustness. Never reuse the test set for tuning.
- Drawdown investigation: performance -> data/backtest audit if suspicious -> risk and robustness.
- Research infrastructure change: systems engineering -> code review -> data/execution/backtest
  audits according to affected semantics. The implementer never certifies the change.
- Suspicious result: data -> execution -> backtest audit -> code review. Do not tune strategy while
  the measurement system is suspect.

## Ownership boundaries

- Hypothesis owns the question and falsification rule, not implementation.
- Signal research owns feature validity, not portfolio outcomes.
- Strategy engineering owns domain code, not risk appetite or generalization.
- Portfolio risk owns risk appetite and sizing constraints, not alpha or implementation validation.
- Data validation owns input fitness, not simulator correctness.
- Execution modelling owns the fill/cost contract, not simulator-wide validity.
- Backtest audit owns end-to-end measurement validity, not calibration or attractiveness.
- Systems engineering owns offline infrastructure implementation, not its validation.
- Experiment operation owns reproducible execution, not adaptive search or interpretation.
- Performance analysis owns descriptive diagnosis, not robustness.
- Robustness owns generalization evidence, not production approval.
- Code review owns engineering quality, not trading edge.
- Evidence curation owns provenance and communication, not any specialist verdict.
- Swing validation owns the final domain gate, never generic-gate waiver or live authority.
