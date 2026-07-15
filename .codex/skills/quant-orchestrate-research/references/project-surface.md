# MatiTradingBot Research Surface

## Architecture

- Interface: `main.py`, `cli/`, Telegram tools, dashboards and reports. Keep strategy rules out.
- Domain/application: `strategies/` and `core/`. Strategies run through the common client contract.
- Data: `data/ohlcv_cache.py`, `data/market_data.py`, and context loaders in `strategies/`.
- Persistence/reporting: `core/database.py`, `reporting/`, journals, and read-only tools.
- Infrastructure: `deploy/`, services, VM, credentials. Outside offline research by default.

Key contracts:

- `strategies/registry.py`: canonical strategy metadata, aliases, warmup, output type, config factory.
- `strategies/base_strategy.py`: strategy interface and journal hooks.
- `strategies/indicators.py`: only active indicator module; `data/indicators.py` is legacy.
- `core/backtest.py`: `BacktestClient`, `BacktestEngine`, execution costs, metrics, historical fetch.
- `cli/runner.py`: shared backtest runner and journal creation.
- `data/ohlcv_cache.py`: deterministic OHLCV cache and contiguity reporting.

## Existing research commands

```powershell
python main.py backtest --strategy <name> --from YYYY-MM-DD --to YYYY-MM-DD --costs realistic
python main.py walk-forward --strategy <name> --costs realistic
python main.py baselines --from YYYY-MM-DD --to YYYY-MM-DD --costs realistic
python main.py sensitivity --from YYYY-MM-DD --to YYYY-MM-DD --costs realistic
python main.py compare --strategies "adaptive,pro" --from 2018 --to 2026
python main.py random-backtest --strategy <name> --windows 10 --months 24 --seed 42
python main.py data-audit
```

Verify `python main.py --help` and command-specific help before relying on documented options.
`baselines` and `sensitivity` are currently Pro-Trend-specific and must not be generalized by
assumption. `walk-forward` uses fixed windows and fixed config; it does not optimize.

Important limitations: `compare` and `random-backtest` do not expose the full cost/config contract;
the generic journal has no dataset hash or repository revision; several robustness tools are
strategy-specific historical scripts rather than a generic platform. Inspect source and record the
actual harness instead of inferring capability from command names.

## Existing research tooling

- Integrity: `tools/data_audit.py`, `tools/audit_costs.py`, `tools/audit_equity_recon.py`,
  `tools/swing_parity_check.py`.
- Signals/structure: `tools/alpha_screens.py`, `tools/swing_phase_attribution.py`,
  `tools/swing_funding_overlay_screen.py`.
- Robustness: `tools/bootstrap_equity.py`, `tools/swing_rolling_start_matrix.py`,
  `tools/swing_ablation_matrix.py`, `tools/sens_phases.py`, `tools/stress_usdt_depeg.py`,
  `tools/delay_sensitivity_replay.py`, and prop challenge/frontier tools.
- Performance/reporting: `tools/journal_summary.py`, `tools/monthly_dist.py`,
  `tools/backtest_report.py`, `tools/strategy_audit.py`, Swing charts and freeze reports.
- Experiment record: `EXPERIMENTS.md`, `backtests/STRATEGY_VERSIONS.md`, strategy plans, and
  forward-test contract/reporting.

Prefer these tools over new parallel scripts. Inspect each tool before running it: several are
strategy-specific, write reports under runtime paths, or encode historical presets.

## Data and statistical constraints

- Canonical BTC 1H cache contains 102931 rows but 102457 distinct timestamps; 474 duplicates are
  known, identical, and protected during forward test.
- Historical fetch uses OKX with Binance fallback and Bitstamp supplementation for early BTC.
- External contexts lag point-in-time inputs: MVRV previous day, market session previous day,
  funding previous complete day. Intraday resamples must exclude incomplete higher-timeframe bars.
- `BacktestResult` includes equity curve, CAGR, Max DD, Sharpe, Sortino, Calmar, underwater duration,
  PF, expectancy, time in market, and trade counts.

## Protected state

Do not modify frozen Swing defaults, `strategies/pro_trend.py`, canonical caches, journals,
`trading.db`, `.env`, runtime files, logs, `graphify-out/`, deployment, or remote services without
the explicit approvals and rollback required by `AGENTS.md`.
