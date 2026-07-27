# MatiTradingBot

> **Current research candidate:** Swing Allocator v7 Cycle Core is a
> `CERTIFIED_CAUSAL_CANDIDATE`, but inactive. It is not the default, is not deployed,
> and has no live or OKX Demo authorization. The frozen default remains Swing v6-2;
> v5 is its rollback/control.

MatiTradingBot is a Python 3.12 research and paper-trading lab for BTC strategies.
It emphasizes deterministic, causal backtests: cached OHLCV is replayed bar-by-bar,
orders use a shared client contract, money uses `Decimal`, and external inputs must
be point-in-time available. Live trading is not authorized.

## Swing v7 Cycle Core

V7 is an isolated, unleveraged BTC/cash allocator with a deliberately narrow
hypothesis: a confirmed-halving clock can avoid the precommitted bear-onset period.
Its fixed allocation is **100% BTC** in post-halving, bull-peak, and accumulation;
**0% BTC** in bear-onset. There are no technical indicators, leverage, shorts,
funding inputs, discretionary overrides, or tactical stable-phase trades.

The candidate evaluates only on UTC four-hour boundaries, reads a completed bar, and
uses a causal fill at the subsequent 1H open. Its persisted transition state fails
closed (`ERROR_LOCKED`) on ambiguous orders, invalid phase/data, or state/journal
errors. V7 has independent shadow and local-paper namespaces; the control-fleet setup
tool cannot register it.

The historical hypothesis is fragile: only two modern cycles are complete, fixed
boundary/delay checks vary materially, and history is in-sample. That is precisely why
the outcome is isolated forward-paper observation—not adoption.

### Certified V7 evidence

| Contract | Value |
|---|---|
| Status | `CERTIFIED_CAUSAL_CANDIDATE`; inactive pending human setup/activation approval |
| Authoritative execution | Immutable `StrategySnapshot` → `TargetIntent`; next-open, fee-reserved reconciled intents |
| Authoritative result | **$54,002,022.18728089349690** final capital from $10,000; 6 timestamp-based next-open operations; reconciliation `PASS` |
| Dataset treatment | Exact duplicate candles are collapsed; conflicting or out-of-order candles fail closed |
| Execution | Completed UTC 4H decisions; 0.10% fee plus 5 bps slippage; fee-reserved fills |
| Certification source | `codex/universal-certification-gate` commit `98fb5ca` and the corrected certified reference |
| Rollback | deactivate only the isolated instance; preserve wallet, transition journal, and evidence |

### Same-window strategy comparator

Only valid results are shown. V7 and BTC buy-and-hold share the same normalized BTC
1H bars, 250-day warmup, UTC 2015-01-01 to 2026-01-01 window, and 0.10% fee + 5 bps
slippage contract. V6 remains useful operational context, but uses protected
historical inputs and is not a matched causal benchmark.

| Strategy | Valid contract | Final capital | CAGR | Max drawdown | Calmar | At-a-glance takeaway |
|---|---|---:|---:|---:|---:|---|
| **Swing v7 Cycle Core** | Certified causal, normalized BTC 1H | **$54.002M** | **118.42%** | -70.49% | **1.68** | 6 phase transitions; 19.77× the matched BTC buy-and-hold final capital |
| **BTC buy & hold** | Same bars, window, warmup, fees, and slippage | $2.731M | 66.61% | -83.77% | 0.80 | Exact matched control; V7 reduced drawdown by 13.28 percentage points |
| **Swing v6-2 default** | Archived protected-input reference, realistic costs | $9.505M | 86.51% | **-52.73%** | 1.64 | Lower historical drawdown; not a causal V7 head-to-head because inputs/cadence differ |

V7’s historical advantage over matched buy-and-hold is descriptive, not forward or
out-of-sample evidence. It must not be read as authorization to change the v6 default.

## Research controls

| Control | Rule |
|---|---|
| Default | Swing v6-2 remains frozen; v5 remains rollback/control |
| Candidate boundaries | V7 does not change v6 files, defaults, paper fleet, or operational instances |
| Historical claims | Historical results are exploratory; adoption requires forward evidence and explicit approval |
| Data | Canonical cache is immutable; retained duplicates are part of its identity |
| Costs | Default research modes: ideal 0.1%/0 bps, realistic 0.1%/5 bps, conservative 0.1%/15 bps |
| Operations | V7 setup, activation, VM access, deployment, Demo ownership, and live trading require separate approval |

## Quick start

```powershell
git clone https://github.com/Caximorris/MatiTradingBot.git
cd MatiTradingBot
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m pytest -q
```

Run a read-only historical backtest:

```powershell
python main.py backtest --strategy swing --from 2015-01-01 --to 2026-01-01 --costs realistic
```

Do not run paper setup, start a bot, deploy, or activate V7 without current explicit
approval. Raw journals can be large; summarize them with
`python tools/journal_summary.py <path>`.

## Documentation

| Document | Purpose |
|---|---|
| [V7 paper readiness](docs/forward-test/v7-cycle-core-paper-readiness.md) | Current candidate contract, reproducible suite, fixed results, and isolation gate |
| [V7 results](docs/SWING_V7_CYCLE_CORE_RESULTS.md) | Earlier and current V7 result packages, provenance, stress evidence, and limitations |
| [V7 plan](docs/SWING_V7_CYCLE_CORE_PLAN.md) | Frozen hypothesis, architecture, state machine, and experiment protocol |
| [V7 deployment plan](docs/SWING_V7_PAPER_DEPLOYMENT_PLAN.md) | Approval-gated VM/shadow/paper topology and rollback |
| [V7 operator runbook](docs/SWING_V7_OPERATOR_RUNBOOK.md) | Read-only status, reconciliation, locks, and promotion evidence |
| [Strategy versions](backtests/STRATEGY_VERSIONS.md) | Historical version record (not a current comparator) |
| [Experiments](EXPERIMENTS.md) | Accepted, rejected, and parked research ideas |
| [Documentation index](docs/README.md) | Complete documentation map |
| [Session state](SESSION.md) | Current operational controls and next safe action |
