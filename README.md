# MatiTradingBot

> **Current production/paper default:** Swing Allocator v6-2 remains frozen; v5 is its rollback/control.
> **Current research focus:** V8 X-Perp is an isolated 2x long/short cycle schedule. Its historical result is a research proxy, not an adopted strategy or authorization to deploy, paper-trade, Demo-trade, or trade live.

MatiTradingBot is a Python research lab for deterministic BTC strategy evaluation and isolated paper operations. It uses UTC timestamps, `Decimal` money, closed-bar decisions, explicit costs, and fail-closed execution boundaries. Live trading is not authorized.

## V8 X-Perp: what it does

V8 follows the confirmed Bitcoin-halving clock. At the `+540 day` bear-onset transition it targets **short 2x**; at the `+900 day` accumulation transition it targets **long 2x**. It holds the target until the next scheduled transition. The isolated operational service is OKX EEA Demo-only, disabled by default, capped below $1,000 actual notional, uses isolated margin, durable intent/recovery state, reconciliation, freshness gates, and a manual-stop latch.

That operational safety work is not a historical accounting model. In particular, the current V8 service has no historical funding ledger, maintenance-margin/tier liquidation replay, or venue-calibrated fill history. Do not read a high historical proxy return as a deploy decision.

## 2018 accumulation-start comparison

The current research window starts on **2018-12-26**, the first accumulation day after the 2016 halving, and ends 2026-06-30 23:00 UTC. It has 65,856 test bars plus 6,000 one-hour warmup bars. The immutable canonical BTC-USDT cache supplies bars through 2026-01-01; a separate in-memory Binance BTCUSDT 1H extension supplies 4,320 bars from 2026-01-02 through June. The canonical cache was not changed.

| Strategy | Position rule | Final from $10k | Return | CAGR | Max DD | Calmar | Operations / fills | Evidence status |
|---|---|---:|---:|---:|---:|---:|---:|---|
| **V6 current-input control** | Long-only BTC allocator; 20–100% target | $236,751 | 2,267.51% | 52.40% | -54.89% | 0.95 | 186 fills / 95 accounting trades | Valid rerun, but funding overlay disabled; not the protected v6-2 anchor |
| **BTC buy & hold** | Buy once, hold BTC | $156,415 | 1,464.15% | 44.22% | -77.19% | 0.57 | 1 economic operation | Matched spot benchmark |
| **V7 phase-policy replay** | 100% BTC outside bear-onset; 0% BTC during bear-onset | $896,586 | 8,865.86% | 81.93% | -70.51% | 1.16 | 4 phase transitions | Research policy replay; the current V7 state-machine rerun locks after its first fill |
| **V8 schedule proxy** | Long 2x outside bear-onset; short 2x during bear-onset | $14,267,352 | 142,573.52% | 162.95% | -81.42% | 2.00 | 4 target transitions | Research-only; funding and OKX maintenance margin are unmodeled |

All rows use a $10,000 initial balance and 0.10% fee plus 5 bps adverse slippage. V6 and buy-and-hold use the repository spot engine. V7 and V8 are explicitly labelled policy/proxy replays because the V7 state machine did not complete this restarted-window run and the V8 execution service is intentionally not a historical simulator.

The complete source identities, contracts, and limitations are in [the V8 comparison record](docs/V8_CYCLE_COMPARISON.md).

## Safety and decision status

| Topic | Current rule |
|---|---|
| Default | V6-2 remains frozen; this document does not change it |
| V8 | Research focus only; deployment structure is unchanged |
| V8 Demo | Dedicated OKX Demo credentials, disabled by default, capped below $1,000 |
| Funding and liquidation | Required before any V8 performance or promotion decision |
| Paper/live | Separate current-task approval is required |

## Quick start

```powershell
git clone https://github.com/Caximorris/MatiTradingBot.git
cd MatiTradingBot
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m pytest -q
```

Run a read-only historical V6 control:

```powershell
python main.py backtest --strategy swing --from 2018-12-26 --to 2026-01-01 --costs realistic
```

## Documentation

| Document | Purpose |
|---|---|
| [V8 comparison record](docs/V8_CYCLE_COMPARISON.md) | Full data lineage, contracts, table, and gaps |
| [V8 Demo canary](docs/ops/v8-xperp-canary.md) | Isolated Demo safety envelope and operator controls |
| [V7 results](docs/SWING_V7_CYCLE_CORE_RESULTS.md) | Certified 2015–2026 V7 reference and limitations |
| [Swing v6 plan](docs/swing/v6-plan.md) | Frozen default and rollback decision record |
| [Strategy versions](backtests/STRATEGY_VERSIONS.md) | Historical strategy chronology |
| [Experiments](EXPERIMENTS.md) | Accepted, rejected, and parked research ideas |
| [Documentation index](docs/README.md) | Documentation map |
