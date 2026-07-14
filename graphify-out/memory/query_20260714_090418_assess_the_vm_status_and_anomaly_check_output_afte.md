---
type: "query"
date: "2026-07-14T09:04:18.711251+00:00"
question: "Assess the VM status and anomaly-check output after pulling c16d804: are v6, Demo, and Prop correct, and what is the next step?"
contributor: "graphify"
outcome: "useful"
source_nodes: ["OKXClient", "._persist_paper_state()", "anomaly_check.py", "build_snapshots()"]
---

# Q: Assess the VM status and anomaly-check output after pulling c16d804: are v6, Demo, and Prop correct, and what is the next step?

## Answer

Expanded from original query via graph vocab: [paper, wallet, prop, demo, journal, anomaly, balance, persist, portfolio, state, status, execution]. The fleet is active and the Demo USDC/Madrid reporting fix is correct. Two persistence/audit defects remain: OKXClient loads a missing paper wallet but does not persist the initial 10000 USDT until a state-changing operation, leaving Prop wallet absent before its first trade; paper_snapshot.discover_bots filters strategy_name LIKE swing%, so anomaly-check does not inspect prop_swing and misses that wallet condition. The Demo 19.2% versus journal 58% gap is a real audit-history mismatch caused by an out-of-band correction, not evidence that the current wallet allocation is wrong. Next local changes should include Prop in snapshots/anomaly checks, persist initial paper wallets at startup, and add an explicit idempotent RECONCILE event/tool for Demo rather than editing the journal or pretending a BUY/SELL occurred.

## Outcome

- Signal: useful

## Source Nodes

- OKXClient
- ._persist_paper_state()
- anomaly_check.py
- build_snapshots()