# v7 `ERROR_LOCKED` reconciliation

`ERROR_LOCKED` is fail-closed: v7 makes no new strategic decision and no new order submission. It is raised for invalid phase/data, corrupted persistent state, failed state persistence, ambiguous submitted orders, and journal persistence failure.

Reconciliation is evidence-first. The operator command records strategy state, wallet, journal path, and recommended no-order resolution. The `--paper` form is a journaled acknowledgement only; it cannot increase exposure. Unlock requires its exact audit id and restores only a neutral state-machine envelope. The next normal evaluation performs ordinary pre-order reconciliation.

Residuals at or below 1% allocation are documented execution-reserve/precision residuals, not tactical retries. Any open/unknown paper order remains locked rather than being resubmitted.
