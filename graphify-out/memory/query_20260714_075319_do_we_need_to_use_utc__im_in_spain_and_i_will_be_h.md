---
type: "query"
date: "2026-07-14T07:53:19.902748+00:00"
question: "do we need to use utc? im in spain and i will be here for a few years, if theres nothing that benefits me using utc y prefer the real time from here, also is there a way to force a rebalance now? this was runnning for an entire day and its still at 57%, something is wrong, the pull i did should afect the demo"
contributor: "graphify"
outcome: "useful"
source_nodes: ["SwingAllocatorBot", "._rebalance()", "._bridge_market()", "demo_config()", "_madrid()"]
---

# Q: do we need to use utc? im in spain and i will be here for a few years, if theres nothing that benefits me using utc y prefer the real time from here, also is there a way to force a rebalance now? this was runnning for an entire day and its still at 57%, something is wrong, the pull i did should afect the demo

## Answer

Expanded via graph vocab: [rebalance,target,daily,closed,cadence,bridge,demo,utc,madrid,run,allocator,cooldown]. Keep database, exchange timestamps, and scheduler state in UTC to avoid DST ambiguity; convert display-only output to Europe/Madrid. The pull did affect the demo code and config, but persistent last_rebalance survived. SwingAllocatorBot checks a default 3-day cooldown before computing target; the filled SELL at 2026-07-13 14:38 UTC blocks retries until roughly July 16. There is no supported force-rebalance CLI. A safe one-off force is to stop services, back up trading.db, clear only last_rebalance and last_eval_block in the swing_allocator_demo internal BotState while preserving initialized, then restart. The structural fix is to avoid arming cooldown when a partial fill leaves allocation outside the rebalance threshold.

## Outcome

- Signal: useful

## Source Nodes

- SwingAllocatorBot
- ._rebalance()
- ._bridge_market()
- demo_config()
- _madrid()