# V7 certified isolated paper candidate operator runbook

This runbook is for a one-month operational observation, not promotion. Statistical robustness remains **FRAGILE**; zero natural V7 transitions in 30 days is possible and is still valid operational evidence.

1. Inspect configuration (read-only): `python tools/v7_paper_setup.py --print-config`
2. Run local dry-run validation (read-only): `python -m pytest -q tests/test_v7_certified_paper.py`
3. Create inactive candidate (**PERSISTENT STATE; later explicit authorization required**): `python tools/v7_paper_setup.py --create-inactive`
4. Verify isolated IDs/paths (read-only): `python tools/v7_paper_setup.py --print-config`
5. Verify paper-only routing (read-only): `python -m pytest -q tests/test_v7_certified_paper.py -k dependency`
6. Activate manually (**NOT IMPLEMENTED; requires separate human authorization and an approved VM deployment procedure**). No command in this repository activates this candidate.
7. Inspect health and daily parity (read-only): `python tools/v7_daily_report.py`
8. Pause (**PERSISTENT STATE; requires later explicit authorization**): set the candidate’s inactive flag through the approved operator procedure; preserve all wallet/journal/evidence files.
9. Review a circuit-breaker event (read-only): inspect `lock_reason`, `lock_timestamp`, and the append-only candidate journal under `data/runtime/v7_certified/v7_certified_paper/`.
10. Resume after explicit approval (**PERSISTENT STATE**): investigate and preserve evidence first; a human must supply a new signed-off reactivation procedure. Do not delete or rewrite state.
11. Deactivate (**PERSISTENT STATE; requires later explicit authorization**): use the same approved operator procedure; never delete evidence.
12. Export the final 30-day evidence package (**PERSISTENT STATE/file export; requires authorization**): copy the candidate-owned wallet, journal, manifest, and daily reports to a new evidence destination; do not overwrite the originals.
13. Roll back (**PERSISTENT STATE; requires later explicit authorization**): deactivate only. V6, the canonical cache, and the V7 evidence remain untouched.

The circuit breaker blocks new paper orders on duplicate intent/order/fill, stale/missing/conflicting/out-of-order candles, hash/configuration mismatch, impossible balance, unavailable paper client, a stuck pending order, wallet mismatch, unexpected regime transition, or repeated unexpected exceptions. It records a UTC reason and remains locked until an explicit human-approved recovery procedure.
