---
type: "query"
date: "2026-07-13T19:38:53.125339+00:00"
question: "track all conections"
contributor: "graphify"
outcome: "useful"
source_nodes: ["OKXClient", "SwingAllocatorBot", "BacktestClient", "BacktestEngine", "RiskManager", "OKXDemoClient", "BotState", "TradeLogger", "telegram_remote.py"]
---

# Q: track all conections

## Answer

Expanded from original query via graph vocab: [okx, client, backtest, engine, swing, allocator, strategy, risk, demo, paper, live, telegram]. OKXClient at core/exchange.py L100 has 82 direct connections: 62 EXTRACTED and 20 INFERRED. Relations: 30 method, 19 uses, 15 imports, 11 references, 4 calls, 1 contains, 1 rationale_for, 1 indirect_call. Two-hop reach is 420 additional nodes across 38 communities. Complete inventory saved in graphify-out/OKXCLIENT_CONNECTION_TRACE.md.

## Outcome

- Signal: useful

## Source Nodes

- OKXClient
- SwingAllocatorBot
- BacktestClient
- BacktestEngine
- RiskManager
- OKXDemoClient
- BotState
- TradeLogger
- telegram_remote.py