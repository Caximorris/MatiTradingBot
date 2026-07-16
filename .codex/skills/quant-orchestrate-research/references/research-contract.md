# Quant Research Contract

## Operating baseline

Read `AGENTS.md` and `SESSION.md` first. Live state in `SESSION.md` overrides historical docs.
Inspect `EXPERIMENTS.md` and `backtests/STRATEGY_VERSIONS.md` before proposing a known idea.

Classify work as exactly one of: `research-only`, `safe-infra`, `observability`, `data-integrity`,
`docs`, `strategy-affecting`, or `forbidden-until-review`. State the classification in reports.

Never read raw multi-megabyte journals. Use `python tools/journal_summary.py ...`. Never mutate
canonical caches, journals, runtime DB/wallets, logs, `graphify-out/`, deployment, or production.
Never start/stop bots, place orders, send messages, or touch live/demo systems without explicit
approval in the current request.

## Research invariants

1. Preregister one causal hypothesis, primary metric, failure criterion, data window, costs, and run
   budget before observing candidate results.
2. Preserve an untouched test or forward period. The BTC 2015-2026 window is closed for new
   optimization; use it only for robustness measurement unless a documented exception applies.
3. Pair comparisons through the same harness with identical candles, window, warmup, costs, and
   execution assumptions. Reproducibility without data integrity is insufficient.
4. Treat closed bars and point-in-time availability as hard constraints. When availability is
   uncertain, lag the input and record the assumption.
5. Apply realistic costs at minimum and conservative costs to finalists. Never repair weak results
   by weakening fees, slippage, risk limits, validation, or look-ahead controls.
6. Distinguish exploratory, confirmatory, and forward evidence. Never describe exploratory results
   as out-of-sample.
7. Record every attempted variant, including failures and inert parameters, in the experiment
   evidence. Do not erase the search path.
8. Keep implementation and certification independent. Run at most one writer agent at a time;
   parallelize only independent read-only gates.

## Metric contract

For all runs report exact strategy/config, symbol, timeframe, UTC window, warmup, cost mode, candle
count, final balance, CAGR, Max DD, Sharpe, Sortino, Calmar/MAR, trades/rebalances, time in market,
and artifact path when available.

For trade strategies also report PF, win rate, expectancy, average win/loss, loss streaks, trade
distribution, and concentration. For allocators, PF/WR are accounting artifacts; prioritize CAGR,
Max DD, Calmar, exposure, churn, `final_btc_qty`, `bnh_initial_btc`, and `btc_vs_bnh_ratio`.

State metric definitions and annualization. Do not mix percent and fraction units, absolute and
annualized returns, or event count and ACB-trade count.

## Evidence and verdicts

Tag claims `[Certain]` for directly observed evidence, `[Likely]` for strong inference, and
`[Guessing]` for gaps. Use one research verdict:

- `SUPPORTED`: preregistered gates passed on valid independent evidence; not automatically promoted.
- `REJECTED`: a kill criterion or integrity-independent performance gate failed.
- `INCONCLUSIVE`: evidence is valid but insufficient or too noisy.
- `BLOCKED`: the required evidence cannot be obtained safely or an approval boundary was reached.

Swing promotion uses the stricter `$mati-swing-validator` verdicts and forward-evidence gate.

Execution assumptions require `$quant-model-execution` when they are new, changed, or material to
the conclusion. Portfolio risk recommendations require `$quant-design-risk`. Final evidence
packages require `$quant-curate-evidence`; polished prose cannot replace a missing gate.

## Completion gate

Before closing, verify command help, relevant tests, deterministic inputs, full diff, `git diff
--check`, and absence of secrets/runtime artifacts. Documentation-only skill changes require skill
validation and reference checks; they do not require strategy backtests.
