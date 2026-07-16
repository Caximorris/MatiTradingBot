# Experiment Record Schema

Use this schema in a report or as the source for an `EXPERIMENTS.md` entry. Do not create a new
registry when the existing file is appropriate.

```markdown
## <experiment-id> — <short title>

- Date (UTC):
- Classification: exploratory | confirmatory | forward
- Repository revision / working-tree state:
- Strategy and resolved config:
- Hypothesis and mechanism:
- Null / kill criterion:
- Baseline:
- Dataset lineage and identity:
- Symbol / timeframe:
- Window / warmup / split:
- Cost and execution model:
- Seed / run budget / completed runs:
- Primary metric:
- Guardrail metrics:
- Commands:
- Artifacts:
- Data validation verdict:
- Backtest audit verdict:
- Results:
- Robustness evidence:
- Limitations / incidents:
- Decision: supported | rejected | inconclusive | blocked
- Reason:
- Rollback / next decisive test:
```

For allocator comparisons include candle count, rebalance-event count, ACB-trade count,
`final_btc_qty`, `bnh_initial_btc`, and `btc_vs_bnh_ratio`. For trade strategies include trade
distribution, PF, expectancy, cost totals, and concentration. Record failed commands and rejected
variants rather than omitting them.
