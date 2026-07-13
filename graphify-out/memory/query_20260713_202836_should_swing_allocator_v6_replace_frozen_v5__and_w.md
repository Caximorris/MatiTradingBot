---
type: "decision"
date: "2026-07-13T20:28:36.235026+00:00"
question: "Should Swing Allocator v6 replace frozen v5, and what else should be improved after mapping all connections?"
contributor: "graphify"
outcome: "useful"
source_nodes: ["SwingAllocatorBot", "BacktestClient", "OKXClient", "OKXDemoClient", "Swing Allocator v6 Research Plan", "Mati Swing Validator"]
---

# Q: Should Swing Allocator v6 replace frozen v5, and what else should be improved after mapping all connections?

## Answer

Paired exact-candle anchor backtests show v6-2 improves final equity, CAGR, profit factor, underwater days, and final BTC quantity without worsening max drawdown or churn. However, current live v5 and v6 behavior has not yet diverged; the first expected divergence is around 2026-10-07. Under the project OOS promotion gate, v6 is NEEDS_MORE_VALIDATION and v5 remains frozen. Updated the validator and project instructions to v5, documented v6 evidence, and added a 12-member shared client-interface contract test covering OKXClient, OKXDemoClient, and BacktestClient.

## Outcome

- Signal: useful

## Source Nodes

- SwingAllocatorBot
- BacktestClient
- OKXClient
- OKXDemoClient
- Swing Allocator v6 Research Plan
- Mati Swing Validator