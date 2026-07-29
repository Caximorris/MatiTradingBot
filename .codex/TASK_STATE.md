Objective: Complete the remaining controls and bounded authenticated evidence for a capped continuous V8 OKX EEA Demo X-Perp canary. Live remains unauthorized.

Classification: explicitly authorized bounded OKX Demo implementation and exercises. Continuous operation must finish disabled and stopped.

Checkpoint:
- Recovery baseline committed as `12501d0 feat(execution): checkpoint v8 recovery controls`.
- Deterministic checkpoint manifest: `artifacts/v8_xperp_recovery/checkpoint_manifest_20260729.json`.
- Baseline full suite 637 passed; V7 exact replay `54002022.18728089349690`, 6 orders.

Milestones:
1. [completed] Preserve scoped recovery checkpoint, hashes, tests, and existing artifacts.
2. [completed] Implement 81-tier parsing/selection and isolated liquidation/margin model.
3. [completed] Run minimum-size authenticated Demo margin comparison and flatten.
4. [completed] Implement separate atomic exact-once funding ledger/reconciliation and deterministic cases.
5. [completed] Close independent emergency-flatten findings and adversarial cases.
6. [completed] Complete capped service, hard risk envelope, kill-switch execution, and commands.
7. [completed] Implement expiry gates and read-only rollover dry-run planner/tests.
8. [completed] Run authenticated rollover dry-run report.
9. [completed] Run bounded capped service open/reconnect/crash/restart/adopt/flat exercise.
10. [completed] Create complete operating runbooks.
11. [completed] Run focused/full validation, V7 replay, final flat/order/process checks.

Current evidence:
- Margin comparison: `artifacts/v8_xperp_canary/margin_comparison_20260729T110435Z.json`.
- All 81 current isolated tiers parsed; tier 1 selected for 0.0001 BTC.
- Actual comparison notional $6.44625 at selected 2x leverage.
- Exchange liquidation 33941.64818325434; conservative local 33959.43097997892518440463646.
- Liquidation distance 47.31909097540597217854623004%, above 35% floor.
- Initial comparison failed closed because OKX `mmr` excludes the separate liquidation-fee reserve; corrected with a regression assertion, rerun passed, and emergency flatten restored zero.
- Funding actual settlement parity remains `UNOBSERVED`: no known V8 position spanned a funding settlement.
- Bounded canary: `artifacts/v8_xperp_canary/bounded_capped_canary_20260729T111357Z.json`.
- Final account: `artifacts/v8_xperp_canary/final_account_20260729T111409Z.json`.
- Capped target $993.38778; maximum actual notional $993.0982606160002.
- Exactly one opening order, three stable fill fragments, forced reconnect blocked execution,
  crash exit 92, restart adopted 0.0154 without duplication, then reduce-only flat.
- Focused V8 tests: 72 passed, 8 SDK deprecation warnings.
- Full repository: 686 passed, 10 known deprecation warnings.
- Compileall, build, changed-file Ruff, Ruff ratchet, and `git diff --check` passed.
- Ruff debt 201 versus checked-in baseline 209 (reduction 8).
- Frozen V7 exact replay passed: `54002022.18728089349690`, 6 orders.

Independent review verdicts:
- Emergency flatten baseline was BLOCK: known orders while flat, visibility lag, account-scoped lock, lineage, and final full-account checks required fixes.
- Margin/funding baseline was UNDERMODELLED; specialist formulas and exact-once identity/state contract are now implemented.
- Canary baseline was BLOCK; hard $1000/2x/loss/freshness/expiry ceilings and unknown-state no-mutation policy are implemented, with operational integration still in progress.

Safety facts:
- No live order has been placed.
- Final authenticated Demo position is zero and all FUTURES/V8 open orders are zero.
- No Python executor process remains.
- Continuous Demo is disabled unless `V8_XPERP_CONTINUOUS_DEMO_ENABLED=true`.
- Selected isolated Demo leverage is now 2x.

Next action:
- Keep continuous Demo stopped. A human may separately authorize a monitored
  continuous observation period after reviewing the committed evidence and runbooks.
