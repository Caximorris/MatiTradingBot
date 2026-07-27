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

### V7 frozen paper-readiness evidence

| Contract | Value |
|---|---|
| Status | `CERTIFIED_CAUSAL_CANDIDATE`; inactive pending human setup/activation approval |
| Authoritative execution | Immutable `StrategySnapshot` → `TargetIntent`; next-open, fee-reserved reconciled intents |
| Authoritative result | **$52,236,346.57893721564825** final capital from $10,000; 6 intents; manifest `VALID` |
| Certification source | `codex/universal-certification-gate` commit `5452f76` |
| Invalid results | `$47.863M` is `INVALID_NON_CAUSAL`; `$13.723M` is `INVALID_INCOMPLETE_EXECUTION_PATH` |
| Causal correction | A fully filled reserve-safe maximum buy is reconciled as complete; partial/rejected/ambiguous fills remain fail-closed |
| Rollback | deactivate only the isolated instance; preserve wallet, transition journal, and evidence |

### Same-window strategy comparator

This is a reporting comparator, not a ranking or promotion table. Rows are shown on
the 2015-01-01 to 2026-01-01 BTC 1H calendar only when that strategy has evidence for
that window. A shared dataset identity and execution manifest are required before a
new row can be called a matched comparison.

| Strategy / version | Window | Cost model | Final capital | CAGR | Max DD | Status / comparability |
|---|---|---|---:|---:|---:|---|
| Swing v7 Cycle Core (certified causal) | Full certified interval | Certified causal contract | **$52.236M** | — | — | `VALID` manifest; historical only |
| BTC buy & hold | — | — | — | — | — | Add only from the same certified manifest family |
| Swing v6-2 frozen default | 2015-2026 | realistic | $9.505M | +86.51% | -52.73% | Archival protected-input reference; **not** a matched V7 rerun |
| V7 legacy client-runner suite | 2015-2026 | realistic | $47.863M | +116.04% | -70.43% | `INVALID_NON_CAUSAL`; forensic only |
| V7 early causal-runner endpoint | 2015-2026 | realistic | $13.723M | — | -77.14% | `INVALID_INCOMPLETE_EXECUTION_PATH`; stopped in `ERROR_LOCKED` |
| Pro Trend v13 | — | — | — | — | — | Frozen/paused; no current matched row |
| Funding Extreme | 2020-06 to 2026-01 | bybit | — | +12.8% | -15.22% | Rejected; different window/execution |
| Prop Swing / CFT | — | — | — | — | — | Retired; not comparable |
| Other legacy strategies | — | — | — | — | — | Dormant; add only after a fixed matched run |

Neither the prior $10–14M results nor the first $40M-ish client-runner results are
eligible for a headline, comparison, or promotion decision. The certified causal
manifest is the only V7 source allowed in the comparator.

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
