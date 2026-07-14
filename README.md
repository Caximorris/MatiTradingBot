# MatiTradingBot

> **Read the name skeptically.** This is not really a "trading bot" that places live trades.
> It's a **backtesting and strategy-research lab** with a live-execution path bolted on — and that
> path runs in **paper (fake-money) mode only**. The flagship strategy makes ~70 trades in 11 years.
> ~95% of the code and effort here is about *measuring strategies honestly*, not running them.

A Python 3.12 CLI (`python main.py ...`) that downloads BTC history from OKX, simulates trading
strategies over it, and obsessively guards against the ways backtests lie to you. It can also run a
strategy "live" against OKX — but only in paper mode, currently deployed on a free Google Cloud VM
and reporting to a Telegram bot. Solo project, ~18 working sessions of iteration.

---

## What it actually does

1. **Downloads** historical BTC OHLCV from OKX and caches it to disk
   (`data/cache/BTC-USDT_1H.json`, ~103k hourly candles, 2014 → 2026).
2. **Simulates** strategies over that history bar-by-bar, with fees + slippage, producing an equity
   curve and a JSON journal of every trade.
3. **Guards** against lookahead bias, overfitting, and unrealistic costs (this is the whole point).
4. **Runs live in paper mode** — simulated fills, no real money — on a GCP free-tier VM.
5. **Reports** via a multi-bot Telegram interface and Rich terminal dashboards.

### The one design decision that matters

A strategy talks to a *client* that fetches candles and places orders. There are three
implementations of that client:

- `OKXClient` (`core/exchange.py`, 771 lines) — the real exchange (live orders, or local
  paper simulation with real market data).
- `BacktestClient` (`core/backtest.py`) — fakes the exact same interface using historical data.
- `OKXDemoClient` (`core/okx_demo_client.py`) — hybrid: real market data (parity with backtest
  intact) + real authenticated orders against OKX's **demo trading** account. The pre-live
  dress rehearsal: it exercises auth, order params, and error handling with fake funds. Because
  the account is on OKX's EEA entity (MiCA: no USDT trading, separate `my.okx.com` API domain),
  it also carries a signal→execution mapping (strategy thinks in BTC-USDT, orders go to BTC-USDC)
  and a two-leg EUR bridge for when the demo engine cancels orders on its half-dead USDC book.

The strategy code **cannot tell which one it's talking to**, so the identical strategy runs in a
backtest, in local paper trading, and against OKX's demo engine with **zero code changes**. That's
the single most important architectural bet in the repo.

```
OKX API → OHLCV candles → disk cache → fed bar-by-bar to strategy
        → strategy emits orders/allocations → engine simulates fills (fees + slippage)
        → equity curve + JSON trade journal
```

---

## The obsession: not lying to yourself

This is what separates the repo from a toy. The rules in `CLAUDE.md` / `SESSION.md` are a discipline
system against the two ways quant backtests deceive you:

- **Lookahead bias — zero tolerance.** Every piece of daily/weekly data used intraday must have
  *closed* before the simulated moment. A list of leaks was found and fixed (MVRV uses yesterday's
  value, VIX uses the prior session, the current 4H block is excluded, funding uses the prior full
  day). A single leak makes a strategy look brilliant in backtest and lose money live.
- **Overfitting protocol.** No change is adopted if it only improves one time window or removes one
  losing trade. The main window is **2015 → 2026** (3 full halving cycles). Candidates are judged by
  **CAGR and Max Drawdown** — explicitly *not* Profit Factor, which proved fragile to the start date.
  The 2015–2026 window is now **closed for optimization**: it's used only to *measure*, not to tune.
- **Determinism.** The OHLCV cache is version-controlled in git, so backtests reproduce
  candle-for-candle across runs and machines.

Money is `Decimal` everywhere (never `float`). Dates are UTC in storage, converted to Europe/Madrid
only in reporting. **257 passing tests** (2026-07-14).

---

## The flagship: Swing Allocator (frozen v6-2)

Not a buy/sell-signal bot — an **allocator**. It decides what percentage of the portfolio sits in
BTC vs cash (floor **20%**, ceiling **100%**, neutral **60%**) and rebalances only when the target
drifts **>10%** and at least **3 days** have passed (~70 rebalances in 11 years).

It nudges that target using the only two signals it trusts:

- **Regime** — EMA50D vs EMA200D + ADX → macro bull or bear? (±0.20)
- **Halving phase** — where in Bitcoin's 4-year cycle are we? (post-halving +0.20, bear-onset −0.30)

Everything else (MVRV, RSI, Pi Cycle, VIX, MACD, funding, DXY) is wired up but **turned off**
(`use_* = False`). Failed ideas weren't deleted — they're left behind config toggles for ablation
testing. The whole config is one big dataclass of levers you flip on or off.

**Why it beats Buy & Hold:** USDT preserved through bear markets buys cheap BTC in the recovery.
In 2022 (BTC −77%) it drops to 20% BTC, preserves capital, and re-accumulates for 2023–2025.

### Swing v6-2 vs BTC Buy & Hold — 2015→2026, realistic costs (0.1% fee + 5 bps)

| Metric | Swing v6-2 | BTC Buy & Hold |
|---|---:|---:|
| Final balance (from $10k) | **$9.505M** | $2.74M |
| **CAGR** | **+86.51%** | +66.6% |
| **Max Drawdown** | **−52.73%** | −83.77% |
| Calmar (CAGR/MaxDD) | **1.64** | 0.80 |
| Rebalances | 70 | 1 (hold) |
| BTC vs B&H | 0.85× | 1.00× |

> **Honest caveats.** Per-trade metrics (PF, win-rate) are per-rebalance and are *not* the verdict —
> that's why the anchors are CAGR, Max DD, Calmar. It ends with *less* BTC than a pure holder
> (0.85×): the thesis is maximizing cycle-adjusted USDT value, not out-accumulating BTC. The −52.7%
> drawdown is judged the **structural floor** for a long-only strategy — backtest optimization is
> declared *done*. The remaining question is forward data: does it hold up on candles it has never
> seen? v6-2 is the frozen paper/default configuration; v5 remains the exact rollback/control.
> No real capital is risked.

---

## Strategy roster

Seven are registered; only one is active.

| Strategy | What it is | Status |
|---|---|---|
| `swing_allocator` | Dynamic BTC/cash allocation | **Default, frozen at v6-2**; v5 rollback/control |
| `pro_trend` | Multi-timeframe trend following (1856 lines) | Paused indefinitely, frozen at v13 |
| `prop_swing` / `funding_extreme` | Prop-firm challenge (someone else's capital) | **Running in paper** (CFT-only candidate); backtest gates not yet met — no challenge purchased |
| `adaptive_trend`, `scalp_momentum`, `range_reversion` | Older experiments | Dormant |

**External-context feeds** (all offset to avoid lookahead): `macro_context.py` (MVRV + halving,
CoinMetrics), `market_context.py` (DXY / NASDAQ / VIX, Yahoo), `funding_context.py` (OKX funding).

---

## Quick start

```bash
git clone https://github.com/Caximorris/MatiTradingBot.git
cd MatiTradingBot
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m pytest -q
```

Reproduce the flagship backtest:

```bash
python main.py backtest --strategy swing --from 2015-01-01 --to 2026-01-01 --costs realistic
```

Run it in paper mode (fake money):

```bash
python tools/paper_fleet_setup.py  # v6 simulated + v6 OKX Demo + Prop Firm
python main.py start        # live/paper — requires explicit intent
python main.py dashboard    # in another terminal
```

Going **live** (`TRADING_MODE=live`, real OKX keys) is possible but requires explicit confirmation;
paper is the default and the current focus.

---

## Key commands

```bash
# Backtesting (continuous, multi-year — balance never resets between years)
python main.py backtest --strategy swing --from 2015-01-01 --to 2026-01-01 --costs realistic
python main.py compare --strategies "adaptive,pro" --from 2018 --to 2026

# Anti-overfitting validation
python main.py walk-forward --strategy swing --costs realistic   # train/test splits
python main.py baselines --from 2018-01-01 --to 2026-01-01       # benchmark allocators
python main.py sensitivity --from 2018-01-01 --to 2026-01-01     # parameter sweeps
python main.py random-backtest --strategy swing --windows 10 --months 24  # random windows

# Forward-test observability (does not change strategy decisions)
python main.py paper-status            # control center for v6/demo/prop bots
python main.py anomaly-check           # infra/data/state red-flags (incl. stale-cron detection)
python main.py forward-report          # metrics from post-start data only
python main.py data-audit              # OHLCV cache integrity (never re-downloads)
python main.py explain --bot v6        # plain-language "why" of an executed rebalance
python main.py reconcile-demo-journal  # audited, idempotent repair after an out-of-band Demo trade

# Spanish IRPF tax report (FIFO, Excel + JSON)
python main.py report --year 2025

# Raw journals can be ~10MB — a hook blocks reading them directly. Use:
python tools/journal_summary.py <path>
```

---

## Live deployment (paper)

Paper bots run 24/7 on a GCP free-tier VM: frozen **v6 simulated**, frozen **v6 on OKX Demo**,
and the **Prop/CFT** candidate. They're controlled remotely through a persistent Telegram button
panel for routine status, reports, charts, audits, and health checks; slash commands remain for
advanced or state-changing operations. The bot also pushes rebalance alerts and daily heartbeats.
systemd (`Restart=always`) keeps the processes alive;
a daily cron runs parity + degradation checks, and `/audit` runs the anomaly engine on demand.
`python main.py status` lists each operable bot and isolated wallet separately; for Demo it shows
the real `BTC-USDC` execution pair and labels cash as USDC while retaining BTC-USDT as the signal
space. Demo performance ratios are intentionally suppressed because simulated fills and real-spot
valuation are not a comparable PnL series.
New simulated portfolios persist their initial $10,000 wallet immediately, so Prop is observable
before its first trade. If Demo was corrected outside the strategy, `reconcile-demo-journal`
appends a distinct `RECONCILE` audit event; it never places an order or rewrites prior history.

Current deployment check (2026-07-14): all three bots have recent heartbeats; the Prop wallet is
persisted at its $10,000 initial balance; Demo's out-of-band allocation correction is recorded as
`RECONCILE` (58.0% → 19.2% BTC); and `main.py anomaly-check` reports no anomalies. The next gate is
forward observation (F13/F15/F19), not another setup migration.

The only credentials on the server are the Telegram token and (for the demo bot) an OKX
**demo-trading** API key — fake funds only, created inside OKX's demo mode. The `demo` bot runs
frozen v6-2 while placing orders on OKX's demo engine,
exercising the real authenticated order path before a single real dollar is at stake (planned
live: September 2026). Its first day already paid for itself: it surfaced a ghost-fill bug
(engine-canceled market orders reported as filled), MiCA compliance blocks (USDT untradeable on
EEA accounts), and the EEA-specific API domain. Runbook:
[`docs/ops/deploy-paper.md`](docs/ops/deploy-paper.md).

---

## Research status

- **Swing v6-2** — the frozen default (v5-equivalent phase router + accumulation-only funding
  overlay). It behaves identically to the v5 control until ~Oct 2026; v5 remains available as an
  exact rollback. Decision record: [`docs/swing/v6-plan.md`](docs/swing/v6-plan.md).
- **Prop firm (Hyro / CFT / Bybit)** — an attempt to pass a funded-account challenge. Backtest
  verdict: the edge is real, but the pass/breach rate doesn't yet meet the firm's gates, so **no
  challenge has been purchased**. The CFT-only candidate is nonetheless **running in paper** on the
  same VM (isolated wallet, its own `/prop` Telegram controls and CFT rule monitor) to gather forward
  data before committing real capital.

---

## Where to look next

| Doc | What's in it |
|---|---|
| [`docs/`](docs/) | Index of all deeper docs (design, audits, ops, forward-test, archive) |
| [`CLAUDE.md`](CLAUDE.md) / [`SESSION.md`](SESSION.md) | Living project brain: conventions, invariants, current state |
| [`EXPERIMENTS.md`](EXPERIMENTS.md) | Experiment registry: every accepted / rejected / parked strategy idea |
| [`docs/handoff.md`](docs/handoff.md) | Full context to resume from another machine |
| [`docs/forward-test/contract.md`](docs/forward-test/contract.md) | Frozen rules of the forward test (start 2026-07-04) |
| [`docs/swing/plan.md`](docs/swing/plan.md) / [`docs/swing/v6-plan.md`](docs/swing/v6-plan.md) | Allocator design + go/no-go criteria |
| [`docs/swing/audits.md`](docs/swing/audits.md) | Quantitative audit of the Swing Allocator (v4 + v5 freeze + F1–F19 plan) |
| [`docs/ops/deploy-paper.md`](docs/ops/deploy-paper.md) | Cloud paper-trading runbook |

---

## Stack

Python 3.12 · typer + rich (CLI) · pandas + pandas-ta · python-okx · aiohttp / urllib
(*deliberately not* `requests`) · SQLAlchemy + SQLite · python-telegram-bot · APScheduler ·
`Decimal` for all money · 257 passing tests.

> **The honest summary:** someone spent months building rigorous machinery to answer *"does this BTC
> allocation strategy actually work, or am I fooling myself?"* — got to "+85% CAGR that survives the
> anti-overfitting gauntlet," froze it, deployed it to paper, and is now waiting on real forward data
> before ever risking a dollar. The engineering quality is in the skepticism, not the strategy.
