---
type: "query"
date: "2026-07-13T19:46:49.181918+00:00"
question: "whats the next step with this info, can we optimize something else? or improve anything?"
contributor: "graphify"
outcome: "useful"
source_nodes: ["OKXClient", "OKXDemoClient", "BacktestClient", "Post-Paper Refactor Backlog", "anomaly_check.py", "funding_refresh.py", "Frozen Forward-Test Contract"]
---

# Q: whats the next step with this info, can we optimize something else? or improve anything?

## Answer

Expanded via graph vocab: [refactor, risk, forward, demo, funding, monitor, parity, bridge, paper, client, test, anomaly]. Current best next step is reliability, not strategy optimization: finish demo bridge/Telegram verification and F15 forward parity; add a test-only client interface contract because OKXDemoClient lacks set_paper_balance and BacktestClient lacks five OKXClient public methods; add funding-cache-stale observability before accumulation because funding_refresh detects staleness only when run with --stale-hours while anomaly_check does not inspect the funding cache. Defer OKXClient/backtest refactor until paper closes and do not tune Swing v5 on the closed 2015-2026 sample.

## Outcome

- Signal: useful

## Source Nodes

- OKXClient
- OKXDemoClient
- BacktestClient
- Post-Paper Refactor Backlog
- anomaly_check.py
- funding_refresh.py
- Frozen Forward-Test Contract