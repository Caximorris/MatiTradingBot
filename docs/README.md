# Documentation index

The current documentation center is Swing v7 Cycle Core: an isolated,
paper-only `CERTIFIED_CAUSAL_CANDIDATE` that remains inactive. It does not
replace the frozen v6-2 default or authorize Demo/live trading.

## Swing v7 — current record

| Document | What it establishes |
|---|---|
| [V7 paper readiness](forward-test/v7-cycle-core-paper-readiness.md) | Current candidate contract and approval-gated isolated-paper boundary |
| [V7 Cycle Core plan](SWING_V7_CYCLE_CORE_PLAN.md) | Hypothesis, immutable clock, fail-closed transitions, and preregistered robustness protocol |
| [V8 cycle comparison](V8_CYCLE_COMPARISON.md) | 2018 accumulation-start V6/V7/V8/B&H research comparison, data lineage, and limitations |
| [V7 results](SWING_V7_CYCLE_CORE_RESULTS.md) | Authoritative $54.002M causal result, matched BTC buy-and-hold control, and limitations |
| [V7 deployment plan](SWING_V7_PAPER_DEPLOYMENT_PLAN.md) | Isolated VM topology, shadow soak gates, and non-destructive rollback |
| [V7 deployment results](SWING_V7_PAPER_DEPLOYMENT_RESULTS.md) | Local-only state and the evidence still required for any remote activation claim |
| [V7 operator runbook](SWING_V7_OPERATOR_RUNBOOK.md) | Status, diagnostics, reconciliation, lock handling, and promotion evidence |
| [ERROR_LOCKED reconciliation](SWING_V7_ERROR_LOCKED_RECONCILIATION.md) | Fail-closed error semantics and journaled no-order recovery |
| [V6→V7 Demo cutover](V7_OKX_DEMO_CUTOVER_RUNBOOK.md) | Separate, approval-gated Demo-account ownership transfer procedure |

## Current controls and comparison sources

| Document | Role |
|---|---|
| [Root README](../README.md) | Current same-window strategy comparator and V7-first overview |
| [Session state](../SESSION.md) | Frozen v6-2 control, inactive V7 candidate, and operational boundaries |
| [Experiments](../EXPERIMENTS.md) | Consolidated accepted/rejected/parked research decisions |
| [Strategy versions](../backtests/STRATEGY_VERSIONS.md) | Historical version chronology; do not treat as a matched comparator |
| [Candidate paper workflow](forward-test/candidate-paper-workflow.md) | Reusable isolated-paper gate modeled on V7 |
| [Forward-test contract](forward-test/contract.md) | Locked v6 control-forward-test rules |

## Historical and specialist references

| Document | Role |
|---|---|
| [Swing v6 plan](swing/v6-plan.md) | Frozen default/rollback decision record |
| [Swing audits](swing/audits.md) | Historical v4/v5 audit and remediation evidence |
| [Swing design plan](swing/plan.md) | Original design/go-no-go history |
| [Paper deployment](ops/deploy-paper.md) | Existing v6/demo control-fleet runbook; not a V7 activation guide |
| [Prop research](prop/hyrotrader-plan.md) | Retired prop-firm research history |
| [Archive](archive/session-archive.md) | Session history; immutable historical reference |
| [Handoff](handoff.md) | Cross-machine context, superseded where it conflicts with `SESSION.md` |
