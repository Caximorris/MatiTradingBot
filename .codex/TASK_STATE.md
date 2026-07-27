# V7 independent integrity and robustness audit

Objective: independently audit normal Swing V7, fail closed on any causal or
accounting discrepancy, and generate reproducible reconciliation evidence.

1. Completed: read the certification commits, manifest, V7 results, and live
   project state; baseline result is invalidated by timestamp-duplicate cadence.
2. Completed: normalize exact duplicate candles and schedule V7 from UTC
   four-hour timestamps; duplicate, missing-row, conflict, and ordering tests
   pass. The timestamp cadence preserves the provisional $54.002M result.
3. In progress: compare every certified order against the standalone reference
   ledger and publish the operation-by-operation reconciliation package.
4. Pending: rerun deterministic robustness/attribution battery and generate
   definitive report only from reconciled evidence.
5. Pending: focused and full validation, diff/status/secret/hash review.

Current evidence: raw certified input produces $52,236,346.57893721564825;
stable exact-timestamp normalization produces $54,002,022.18728089349690 and
changes five fill timestamps.  The current manifest cannot remain authoritative.

Next action: capture and compare the six certified orders against the standalone
reference fields, then regenerate the robustness suite from that identity.
