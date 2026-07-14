---
type: "query"
date: "2026-07-14T08:26:11.976638+00:00"
question: "CFT monitor sin datos after activating PropSwing"
contributor: "graphify"
outcome: "useful"
source_nodes: ["PropSwingBot", "update_status()", "cft_monitor.py", "live_cmds.py"]
---

# Q: CFT monitor sin datos after activating PropSwing

## Answer

Expanded via graph vocab: [prop, cft, monitor, status, update, run, bot, state]. PropSwingBot.run calls _update_cft_monitor on every successful tick after loading at least 1000 OHLCV rows. Therefore an absent CFT status after activation means the first Prop tick has not completed, returned early for insufficient OHLCV, or raised an error before monitor update; inspect matibot logs.

## Outcome

- Signal: useful

## Source Nodes

- PropSwingBot
- update_status()
- cft_monitor.py
- live_cmds.py