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

A strategy talks to a *client* that fetches candles and places orders. There are two
implementations of that client:

- `OKXClient` (`core/exchange.py`, 771 lines) — the real exchange.
- `BacktestClient` (`core/backtest.py`) — fakes the exact same interface using historical data.

The strategy code **cannot tell which one it's talking to**, so the identical strategy runs in a
backtest and in live paper trading with **zero code changes**. That's the single most important
architectural bet in the repo.

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
only in reporting. 179 passing tests.

---

## The flagship: Swing Allocator (frozen v5)

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

### Swing v5 vs BTC Buy & Hold — 2015→2026, realistic costs (0.1% fee + 5 bps)

| Metric | Swing v5 | BTC Buy & Hold |
|---|---:|---:|
| Final balance (from $10k) | **$9.14M** | $2.74M |
| **CAGR** | **+85.84%** | +66.6% |
| **Max Drawdown** | **−52.73%** | −83.77% |
| Calmar (CAGR/MaxDD) | **1.63** | 0.80 |
| Sharpe / Sortino | 1.38 / 1.57 | 1.08 / 1.28 |
| Rebalances | 70 | 1 (hold) |
| BTC vs B&H | 0.82× | 1.00× |

> **Honest caveats.** Per-trade metrics (PF, win-rate) are per-rebalance and are *not* the verdict —
> that's why the anchors are CAGR, Max DD, Calmar. It ends with *less* BTC than a pure holder
> (0.82×): the thesis is maximizing cycle-adjusted USDT value, not out-accumulating BTC. The −52.7%
> drawdown is judged the **structural floor** for a long-only strategy — backtest optimization is
> declared *done*. The remaining question is forward data: does it hold up on candles it has never
> seen? v5 is frozen (`swing-v5-frozen`) pending paper/forward validation; no real capital risked.

---

## Strategy roster

Seven are registered; only one is active.

| Strategy | What it is | Status |
|---|---|---|
| `swing_allocator` | Dynamic BTC/cash allocation | **Default, frozen at v5** |
| `pro_trend` | Multi-timeframe trend following (1856 lines) | Paused indefinitely, frozen at v13 |
| `prop_swing` / `funding_extreme` | Prop-firm challenge (someone else's capital) | Research — **rejected** (edge real, pass/breach gates not met) |
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
python main.py bot add swing BTC-USDT
python main.py bot enable swing_allocator_btc_usdt BTC-USDT
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

# Forward-test observability (read-only, never touches the strategy)
python main.py paper-status            # control center for v5/v6/legacy bots
python main.py anomaly-check           # infra/data/state red-flags
python main.py forward-report          # metrics from post-start data only
python main.py data-audit              # OHLCV cache integrity (never re-downloads)

# Spanish IRPF tax report (FIFO, Excel + JSON)
python main.py report --year 2025

# Raw journals can be ~10MB — a hook blocks reading them directly. Use:
python tools/journal_summary.py <path>
```

---

## Live deployment (paper)

Three paper bots (Swing **v5 / v6 / legacy**) run 24/7 on a GCP free-tier VM, each with an isolated
fake wallet (`paper_state_<id>.json`), controlled remotely via a multi-bot Telegram interface
(`/status`, `/report`, `/equity`, `/bots`) that pushes rebalance alerts and daily heartbeats.
systemd (`Restart=always`) keeps the processes alive; a daily cron runs parity + degradation checks.

No API keys live on the server (paper uses only public OKX data). Runbook: [`DEPLOY_PAPER.md`](DEPLOY_PAPER.md).

---

## The two side-quests

- **Swing v6** — an experimental successor (phase-router + funding overlay) that, *by design*,
  behaves identically to v5 until ~Oct 2026, so the paper A/B test produces no signal until then.
  Research plan: [`SWING_V6_PLAN.md`](SWING_V6_PLAN.md).
- **Prop firm (Hyro / CFT / Bybit)** — an attempt to pass a funded-account challenge. Verdict: the
  edge is real, but the pass/breach rate doesn't meet the firm's gates. **Parked.**

---

## Where to look next

| Doc | What's in it |
|---|---|
| [`CLAUDE.md`](CLAUDE.md) / [`SESSION.md`](SESSION.md) | Living project brain: conventions, invariants, current state |
| [`HANDOFF_2026-07-05.md`](HANDOFF_2026-07-05.md) | Full context to resume from another machine |
| [`FORWARD_TEST_CONTRACT.md`](FORWARD_TEST_CONTRACT.md) | Frozen rules of the forward test (start 2026-07-04) |
| [`SWING_PLAN.md`](SWING_PLAN.md) / [`SWING_V6_PLAN.md`](SWING_V6_PLAN.md) | Allocator design + go/no-go criteria |
| [`DEPLOY_PAPER.md`](DEPLOY_PAPER.md) | Cloud paper-trading runbook |

---

## Stack

Python 3.12 · typer + rich (CLI) · pandas + pandas-ta · python-okx · aiohttp / urllib
(*deliberately not* `requests`) · SQLAlchemy + SQLite · python-telegram-bot · APScheduler ·
`Decimal` for all money · 179 passing tests.

> **The honest summary:** someone spent months building rigorous machinery to answer *"does this BTC
> allocation strategy actually work, or am I fooling myself?"* — got to "+85% CAGR that survives the
> anti-overfitting gauntlet," froze it, deployed it to paper, and is now waiting on real forward data
> before ever risking a dollar. The engineering quality is in the skepticism, not the strategy.
