---
type: "query"
date: "2026-07-14T09:19:15.947296+00:00"
question: "Implement Prop snapshot coverage, immediate initial paper-wallet persistence, and an idempotent audited Demo journal reconciliation command."
contributor: "graphify"
outcome: "useful"
source_nodes: ["OKXClient", "._persist_paper_state()", "build_snapshots()", "anomaly_check.py", "telegram_remote.py"]
---

# Q: Implement Prop snapshot coverage, immediate initial paper-wallet persistence, and an idempotent audited Demo journal reconciliation command.

## Answer

Expanded from graph vocab: [paper, wallet, prop, demo, journal, anomaly, balance, persist, portfolio, state, snapshot, execution]. Implemented three infrastructure-only fixes without changing frozen v6-2 decisions: paper_snapshot now includes operable swing_allocator and prop_swing rows; OKXClient writes a new persisted paper wallet during construction before the first order; reconcile-demo-journal validates the OKX Demo mirror, calculates with Decimal, and appends a distinct RECONCILE event carrying exact tracked balances, reason, quote alias metadata, and a wallet fingerprint. Repeated reconciliation of the same latest snapshot is a no-op, while a later stale operation can be superseded. RECONCILE remains visible as an audit event but is excluded from strategy rebalance counts. Full suite: 257 passed.

## Outcome

- Signal: useful

## Source Nodes

- OKXClient
- ._persist_paper_state()
- build_snapshots()
- anomaly_check.py
- telegram_remote.py