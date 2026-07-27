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
4. Completed with limitations: corrected robustness checkpoint includes temporal
   reslices and 24/72/168/720h moving/stationary block samples; definitive HTML
   and render PNG are in `.v7-final-report`. Frozen V6 has no certified adapter
   (`strategies.registry.get('swing_allocator').certified_factory is None`), so
   no causal V6 result may be substituted.
5. In progress: full validation, diff/status/secret/hash review.

Current evidence: raw certified input produces $52,236,346.57893721564825;
stable exact-timestamp normalization produces $54,002,022.18728089349690 and
changes five fill timestamps.  The current manifest cannot remain authoritative.

Next action: run final repository validation and commit report/suite sources.
