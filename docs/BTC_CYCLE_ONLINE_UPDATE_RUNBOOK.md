# BTC Cycle Online Update Runbook

## Daily read-only job

```powershell
python tools/btc_cycle_daily_update.py --start 2015-01-01
```

The job queries the current block height, verifies blocks 210000/420000/630000/840000, stores a
separate estimated-next-halving record, fetches public daily candles, validates them, rebuilds the
consensus, updates provisional current-cycle labels, and writes alerts/evidence only.

Recommended schedule: after UTC close daily; run the full historical audit weekly. Run the heavy
5x5, placebo, and LOCO jobs only after a dataset hash changes or by manual research authorization.

## Immutable state

- `confirmed_halvings` and `estimated_next_halving` are separate records.
- `data/btc_cycle_audit/snapshots/` is append-only and content addressed.
- `original_prediction.json` is created once for the 2024 cycle and cannot be rewritten.
- `current_observation.json`, `revised_research_candidate.json`, and `active_production_policy.json`
  are separate namespaces.

## Alerts

Alerts are informational: stale provider, source disagreement, revision, missed expected window,
new high after bear-defense start, new low after accumulation start, placebo match, candidate
underperformance, material halving-estimate change, and look-ahead risk. No alert writes targets,
orders, strategy config, runtime DB, or paper/live state.

## Recovery

If a source fails, preserve the failed manifest and rerun later. If a provider revises a row, retain
the old snapshot and create a new hash. Never deduplicate or regenerate the protected `data/cache`
files. If a candidate is suggested, keep the active configuration unchanged and require the full
research gate plus explicit approval before any strategy change.
