# V7 independent integrity and robustness audit

Objective: independently audit normal Swing V7, fail closed on any causal or
accounting discrepancy, and generate reproducible reconciliation evidence.

1. Completed: read the certification commits, manifest, V7 results, and live
   project state; baseline result is invalidated by timestamp-duplicate cadence.
2. In progress: normalize exact duplicate candles at the certified-engine
   boundary and add adversarial contract tests.
3. Pending: independent reference implementation and exact trade/equity
   reconciliation package.
4. Pending: rerun deterministic robustness/attribution battery and generate
   definitive report only from reconciled evidence.
5. Pending: focused and full validation, diff/status/secret/hash review.

Current evidence: raw certified input produces $52,236,346.57893721564825;
stable exact-timestamp normalization produces $54,002,022.18728089349690 and
changes five fill timestamps.  The current manifest cannot remain authoritative.

Next action: patch `core/certification.py` to collapse only byte-identical
duplicate candles and reject conflicting/non-monotonic input.
