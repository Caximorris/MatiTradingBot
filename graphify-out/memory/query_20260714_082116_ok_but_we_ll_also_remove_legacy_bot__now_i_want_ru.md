---
type: "query"
date: "2026-07-14T08:21:16.812978+00:00"
question: "ok but we'll also remove legacy bot, now i want running v6 and prop firm, v6 on both demo and simulated"
contributor: "graphify"
outcome: "useful"
source_nodes: ["BotState", "SwingAllocatorBot", "OKXDemoClient", "PropSwingBot", "registry.py"]
---

# Q: ok but we'll also remove legacy bot, now i want running v6 and prop firm, v6 on both demo and simulated

## Answer

Expanded from original query via graph vocab: [registry, registrar, active, bots, swing, allocator, demo, paper, prop, setup, legacy, state]. BotState is reconciled by tools/paper_fleet_setup.py using the explicit v6 simulated, OKX Demo, and Prop Firm configs. The true legacy registration/state is removed, other runnable bots such as v5 are disabled, and internal v6/demo/prop state rows are preserved but filtered from observability.

## Outcome

- Signal: useful

## Source Nodes

- BotState
- SwingAllocatorBot
- OKXDemoClient
- PropSwingBot
- registry.py