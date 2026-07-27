# V7 independent integrity and robustness audit

Objective: independently audit normal Swing V7, fail closed on any causal or
accounting discrepancy, and generate reproducible reconciliation evidence.

1. Completed: read the certification commits, manifest, V7 results, and live
   project state; baseline result is invalidated by timestamp-duplicate cadence.
2. Completed: normalize exact duplicate candles and schedule V7 from UTC
   four-hour timestamps; duplicate, missing-row, conflict, and ordering tests
   pass. The timestamp cadence preserves the provisional $54.002M result.
3. Completed: certified and independent ledgers reconcile exactly for all six
   operations; `.v7-operation-audit/reconciliation.json` is PASS.
4. In progress: corrected core robustness matrix (boundaries, costs, delays,
   and calendar placebos) is checkpointed in `.v7-corrected-robustness`.
   Bootstrap, temporal windows, attribution, and definitive report remain.
5. Pending: focused and full validation, diff/status/secret/hash review.

Current evidence: raw certified input produces $52,236,346.57893721564825;
stable exact-timestamp normalization produces $54,002,022.18728089349690 and
changes five fill timestamps.  The current manifest cannot remain authoritative.

Next action: add temporal/attribution/bootstrap cases to the corrected suite
and emit a report only from its checkpoint and reconciled ledger.
