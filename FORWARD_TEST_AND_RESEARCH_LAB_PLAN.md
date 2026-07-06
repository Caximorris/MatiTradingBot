# FORWARD_TEST_AND_RESEARCH_LAB_PLAN.md

> Tracking document. Evolves MatiTradingBot from a "trading bot" into a **BTC allocation
> research lab + paper-forward-test control system**, WITHOUT contaminating the running
> v5/v6/legacy forward test.
>
> **Created:** 2026-07-06 | **Owner:** Mati | **Status doc, not code.** Nothing here is
> implemented yet. Read `CLAUDE.md` + `SESSION.md` before acting on any task.
>
> This plan was written after inspecting the actual repo. It reuses existing modules and
> naming conventions and does NOT invent parallel infrastructure where an equivalent already
> exists. Where a task overlaps a frozen/strategy-adjacent code path, it is flagged explicitly.

---

## 0. How to use this document

Every task uses this block:

```
- [ ] <Task title>
    - Priority:            P0 | P1 | P2 | P3
    - Status:              Not started | In progress | Blocked | Done | Rejected | Parked
    - Forward-test safe:   YES | YES-if-isolated | NO | FORBIDDEN-until-review
    - Risk:                Low | Medium | High
    - Depends on:          <task ids or "none">
    - Files likely involved: <real paths>
    - Acceptance criteria: <checklist>
    - Notes:               <caveats>
```

**Classification legend (see Section 2):** every code change must be tagged as one of
`safe-infra`, `observability`, `data-integrity`, `docs`, `strategy-affecting`,
`forbidden-until-review`.

## Progress log

- **2026-07-06** — Phase 1 + first observability wave shipped (read-only, forward-safe):
  T3.1, T4.2, T4.1, T13.1, T6.1, T7.1. 26 new tests (179/179 total). New files:
  `FORWARD_TEST_CONTRACT.md`, `tools/paper_snapshot.py`, `tools/anomaly_check.py`,
  `tools/forward_report.py`, `tools/data_audit.py`, `cli/paper_cmds.py` (+ `main.py` reg).
  - **DATA FINDING (T7.1, unactioned by design):** `data-audit` found **474 exact-duplicate
    rows** in the canonical `BTC-USDT_1H` cache, clustered at the 2017 Bitstamp->OKX gap-fill
    seam. All duplicates are identical OHLCV (0 conflicting values), so no backtest value is
    wrong, but the "102931 velas" count is inflated — true distinct = **102457**. NOT fixed:
    dedup would be a forbidden cache mutation mid-forward-test (contract §4/§6c) and would shift
    parity. Logged here; revisit only after the forward test, and via git-tracked change.

**Forward-test-safe legend:**
- `YES` — pure read / new isolated file / docs. Cannot touch a decision.
- `YES-if-isolated` — safe ONLY if it writes to a NEW sink and does not alter existing
  control flow, config defaults, or the frozen decision path. Must be code-reviewed for that.
- `NO` — changes runtime behavior of a running bot; do outside the forward test or on a
  non-participating instance only.
- `FORBIDDEN-until-review` — would alter frozen strategy logic/params/signals; blocked by
  Section 2 until an explicit forward-test review milestone.

---

## 1. Objective

Turn this project from "a bot that trades" into a **disciplined research + monitoring lab**
around a frozen BTC allocation strategy (Swing v5, tag `swing-v5-frozen`).

The near-term goal is **NOT** to raise CAGR or optimize the strategy. The 2015-2026 window is
CLOSED for optimization (SESSION.md rule 5). Instead:

- Monitor live paper behavior of the 3 deployed bots (v5 / v6 / legacy).
- Validate execution stability (heartbeats, VM health, API reliability).
- Detect data and execution anomalies before they silently corrupt the experiment.
- Compare v5 vs v6 vs legacy forward behavior (note: v6 == v5 in live until ~2026-10-07).
- Preserve experiment integrity — no post-hoc reinterpretation, no tuning on forward data.
- Make every decision auditable (why a rebalance did / did not happen).
- Package the project as a serious, honest, portfolio-quality engineering artifact.

**Success = we can answer "is the strategy behaving as designed, and is the data/execution
trustworthy?" with evidence — not "did we make more money this week?".**

---

## 2. Non-negotiable rules

These override any task below. A task that violates one does not ship, even if a backtest
improves.

1. **Do not change frozen strategy logic during the forward-test period.** `strategies/swing_allocator.py`
   decision path (roughly the `_decide`/signal-assembly block, lines ~300-510, and the
   rebalance gate) is FROZEN. No new signals, no changed deltas/thresholds, no new gates.
2. **Do not tune parameters on forward data.** No config default changes derived from what
   paper did this week/month.
3. **Do not adopt changes based only on one good/bad paper event.** One divergence, one bad
   rebalance, one drawdown spike is a data point, not a mandate.
4. **Do not change historical backtest assumptions** (costs, warmup, cache, fill model in
   `core/backtest.py`, `data/ohlcv_cache.py`) unless the change is explicitly marked
   `safe-infra` / `data-integrity` AND is behavior-preserving for existing anchors
   (verified via `tools/swing_v5_freeze_report.py` and `tools/swing_parity_check.py`).
5. **Do not use the closed 2015-2026 window for further strategy tuning.** It is for
   measuring robustness only (SESSION.md rule 5). Simplification-only exceptions still apply.
6. **Every code change is classified as exactly one of:**
   - `safe-infra` — new tooling that cannot alter a decision (new CLI report, new file writer).
   - `observability` — reads state/logs and presents it. No writes to strategy sinks.
   - `data-integrity` — audits/validates data; may add checks, never silently mutates cache.
   - `docs` — Markdown / diagrams / README.
   - `strategy-affecting` — touches decision logic/params/signals/allocation. BLOCKED during
     forward test unless it is a genuine bug that invalidates the experiment (then: stop,
     document, treat as an experiment restart per the Contract).
   - `forbidden-until-review` — anything queued for the post-forward-test review gate.
7. **Config defaults stay put.** New behavior ships behind a NEW flag defaulting to the
   current value (the repo's established pattern — see `SwingAllocatorConfig` toggles).
8. **New observability must not add latency/side effects to the live tick.** Prefer a separate
   process (like `tools/telegram_remote.py` already runs) reading the same DB/JSONL.

---

## 3. Forward Test Contract

Create a canonical, human-readable contract that freezes the rules of the experiment BEFORE
we read more results, so nothing can be reinterpreted after the fact.

- [x] **T3.1 — Author `FORWARD_TEST_CONTRACT.md`** (prefer Markdown over YAML: humans read it,
      reports link to it; a machine-readable `forward_test_contract.yaml` can mirror the
      metrics block later if a report needs to parse it).
    - Priority:            P0
    - Status:              Done (2026-07-06; start date 2026-07-04, mirrored in forward_report.py)
    - Forward-test safe:   YES (docs)
    - Risk:                Low
    - Depends on:          none
    - Files likely involved: `FORWARD_TEST_CONTRACT.md` (new), references `SESSION.md`,
      `DEPLOY_PAPER.md`, `SWING_V6_PLAN.md`, `data/runtime/`.
    - Acceptance criteria:
        - [ ] Contract file exists at repo root.
        - [ ] Human-readable, no code required to understand it.
        - [ ] Clearly separates STRATEGY failure from INFRASTRUCTURE failure.
        - [ ] Future reports (Section 6) can cite it by section number.
        - [ ] Prevents post-hoc reinterpretation (locked start date + locked metric defs).
    - Notes: Content must include, at minimum:
        - **Forward test start date** (the deploy/reset baseline; pull from `DEPLOY_PAPER.md`
          and the earliest `swing_rebalances.jsonl` INIT per bot — do not guess).
        - **Variants under test:** v5 (frozen default), v6 (`SWING_V6_PLAN.md`, phase router +
          funding overlay), legacy (`paper_state.json` bot).
        - **Paper wallets:** `data/runtime/paper_state_<id>.json` per bot; legacy shared
          `paper_state.json`. Map each `instance_id` -> wallet file.
        - **Allowed interventions:** restart VM/process, restart Telegram service, fix
          observability code, restore cache from git, patch data-integrity tooling.
        - **Forbidden interventions:** edit strategy code/params, re-tune, delete/rewrite
          journals, reset a wallet mid-test, swap the canonical data source.
        - **Evaluation date + minimum observation period:** v6 vs v5 divergence not expected
          until ~2026-10-07 (day 900, bear_onset->accumulation). State a minimum window past
          that before ANY v6 judgment.
        - **Metrics tracked:** equity, drawdown, rebalance count, exposure stats, v5/v6/legacy
          divergence, uptime, data-gap count. Definitions locked here.
        - **Failure conditions & invalidation rules:**
            - *Real forward-test failure* = strategy behaves as designed but outcome breaches a
              pre-declared bound (e.g. drawdown beyond backtest envelope) over the min window.
            - *Infrastructure failure* = missed heartbeats, VM down, API errors, missing
              candles, Telegram/reporting down — INVALIDATES the affected window, does NOT
              count against the strategy.
            - *Invalidation* = any lookahead leak, cache mutation, or code change to the frozen
              path found mid-test voids results from that point; document and restart the clock.
        - **Downtime / API errors / missing candles / reporting failures:** each gets a
          written handling rule (log, classify as infra, backfill from cache-only, annotate the
          forward report's "infra incidents" section).

---

## 4. Unified Paper Bot Control Center

A single interface to see all running paper bots at a glance.

**Recommendation (after repo inspection): extend the existing Rich stack, do NOT add
Streamlit/FastAPI/React yet.** Reasons: (a) `reporting/dashboard.py` + `cli/live_cmds.py
dashboard` already exist and use Rich; (b) `tools/tg_views.py` already computes almost every
field below as pure functions (`format_status`, `_bot_row`, `_perf_ratio`, heartbeat parsing);
(c) the VM is a headless e2-micro — a terminal/Telegram surface fits the ops model in
`DEPLOY_PAPER.md`; a web server is extra attack surface + deploy work for one user. Revisit
Streamlit/HTML only for the Portfolio demo (Section 15), as a read-only export.

- [x] **T4.1 — `okx-trader paper-status` command (multi-bot Rich control center)**
    - Priority:            P0
    - Status:              Done (2026-07-06; `cli/paper_cmds.py:paper_status`, `--watch`)
    - Forward-test safe:   YES (observability; read-only over DB + runtime files)
    - Risk:                Low
    - Depends on:          none (T3 recommended first for context)
    - Files likely involved: new `cli/paper_cmds.py` (register in `main.py`), reuse
      `tools/paper_bots.py` (`bot_label`, `paper_state_path`, `filter_rebalances`),
      `tools/tg_views.py` (`format_status`, `_bot_row`, `_perf_ratio`), `core/database.py`
      (`BotState`, `Trade`, `Position`), `data/runtime/*.json*`,
      `data/runtime/swing_rebalances.jsonl`, `data/runtime/tg_state.json`,
      `data/runtime/daily_checks.log`.
    - Acceptance criteria:
        - [ ] A single command launches it (`python main.py paper-status`, `--watch` for live).
        - [ ] Displays all 3 paper bots (discovered via `BotState.strategy_name LIKE 'swing%'`,
              excluding the `swing_allocator` state row, mirroring `telegram_remote.swing_bot_rows`).
        - [ ] Does NOT import or touch strategy decision logic.
        - [ ] Reads from existing persistence/logging (DB, paper_state files, JSONL, tg_state).
        - [ ] Clearly marks STALE data (age vs `LIVENESS_MAX_AGE_MIN` in `tg_views`).
    - Notes: Fields to show per bot (all sourced from existing state; mark "n/a" where the
      source does not yet exist rather than inventing it):
      active bot + label (v5/v6/legacy), strategy version, fake wallet balance (paper_state
      file), BTC/cash split + BTC exposure %, last decision ts (`last_run` / last JSONL entry),
      last rebalance (JSONL), next possible rebalance window (`_next_4h_eval` + 3-day cooldown),
      current drawdown + equity (needs T6 equity helper), realized/unrealized PnL
      (`Trade.pnl` / `Position.unrealized_pnl` — paper swing may not populate Position; mark
      n/a honestly), last heartbeat (`daily_checks.log` / `tg_state.json`), VM/process health
      (`daily_checks.sh` output if present), Telegram status (`tg_state.json`), OKX connectivity
      (probe via existing client, read-only), DB connectivity, latest warning/error (loguru
      log tail), paper-vs-backtest divergence (from `tools/swing_parity_check.py` if available).

- [x] **T4.2 — Shared snapshot builder (pure function) feeding CLI + Telegram + reports**
    - Priority:            P1
    - Status:              Done (2026-07-06; `tools/paper_snapshot.py:build_snapshots`; telegram_remote consolidation parked)
    - Forward-test safe:   YES (observability)
    - Risk:                Low
    - Depends on:          T4.1
    - Files likely involved: extend `tools/paper_bots.py` or new `tools/paper_snapshot.py`;
      consumed by `cli/paper_cmds.py`, `tools/telegram_remote.py`, Section 6 report.
    - Acceptance criteria:
        - [ ] One pure function returns a per-bot snapshot dict (no I/O side effects beyond reads).
        - [ ] Unit-testable without starting any service (pattern of `tests/test_paper_bots.py`).
        - [ ] Reused by at least CLI + one report to avoid divergent field logic.
    - Notes: Keeps DRY with the existing `tg_views` formatters; those become thin renderers.

---

## 5. Decision Explanation View

Inspect WHY a bot made — or did not make — a decision.

**Critical gap found in repo:** `swing_allocator._log_rebalance` (line ~760) only records
events where a rebalance actually executed (INIT/BUY/SELL), with fields
`btc_pct_before/target/after`, `price`, `qty`, `portfolio_usdt`, `signals`. It stores NOTHING
for a SKIPPED decision or the signal state on a no-op tick. So "why NO rebalance" cannot be
reconstructed from current logs.

- [ ] **T5.1 — Explain a KNOWN rebalance from existing journals (read-only, ship first)**
    - Priority:            P1
    - Status:              Not started
    - Forward-test safe:   YES (observability; parses `swing_rebalances.jsonl` + swing journals)
    - Risk:                Low
    - Depends on:          none
    - Files likely involved: new `tools/decision_explain.py` + `okx-trader explain`
      (in `cli/report_cmds.py` or new `cli/paper_cmds.py`); reads `swing_rebalances.jsonl`,
      `reporting/swing_journal.py` output, `strategies/swing_phase_policy.py` for phase labels.
    - Acceptance criteria:
        - [ ] Inspect a specific date or the latest decision.
        - [ ] Plain-English output (regime signal, halving phase, prior/target/actual alloc,
              threshold, cooldown status, est. fees/slippage, reason).
        - [ ] Works in CLI; format reusable by Telegram/dashboard.
        - [ ] Does NOT alter strategy behavior.
        - [ ] Renders the `signals` list already stored per rebalance into readable causes.
    - Notes: This works TODAY for executed rebalances without touching the strategy.

- [ ] **T5.2 — Capture SKIPPED-decision context (the missing "why not")**
    - Priority:            P2
    - Status:              Blocked (needs isolation review)
    - Forward-test safe:   YES-if-isolated (writes a NEW sink only; must not change control flow)
    - Risk:                Medium
    - Depends on:          T5.1, T3 (contract must classify this as observability, not a change)
    - Files likely involved: `strategies/swing_allocator.py` (ADD a decision-trace hook that
      appends to a NEW `data/runtime/swing_decisions.jsonl`), guarded by a NEW config flag
      `emit_decision_trace: bool = False` (default False = identical behavior).
    - Acceptance criteria:
        - [ ] With the flag OFF, byte-for-byte identical behavior + identical anchors
              (verified via `tools/swing_v5_freeze_report.py` and `tools/swing_parity_check.py`).
        - [ ] With the flag ON, every tick emits target-vs-actual + gate reason (threshold not
              met / cooldown active) to the new JSONL, and NOTHING else changes.
        - [ ] Output shows whether all inputs were available without lookahead
              (echo the closed-bar timestamps used).
        - [ ] Code review confirms no change to the decision/rebalance math.
    - Notes: **This is the one task that touches the frozen file.** It must be additive
      logging behind a default-OFF flag, reviewed against Section 2 rule 1/7. If review finds
      any behavior delta, it becomes `forbidden-until-review`. Enabling it on a LIVE forward
      bot changes nothing numerically but should still be a conscious, contract-logged choice.

---

## 6. Forward-Only Reporting

Reports that use ONLY data at/after the forward-test start date, structurally unable to leak
historical backtest data.

- [x] **T6.1 — `okx-trader forward-report` command**
    - Priority:            P0
    - Status:              Done (2026-07-06; `tools/forward_report.py` + CLI; hard pre-start filter + assert)
    - Forward-test safe:   YES (observability)
    - Risk:                Low
    - Depends on:          T3 (start date), T4.2 (snapshot builder) recommended
    - Files likely involved: new `tools/forward_report.py` + register in `cli/report_cmds.py`;
      reuse `tools/report_common.py`, `reporting/swing_journal.py`, `core/database.py`,
      `data/runtime/swing_rebalances.jsonl`, `daily_checks.log`; export via same Markdown/HTML
      pattern as `tools/backtest_report.py` (+ `*_template.html`).
    - Acceptance criteria:
        - [ ] CANNOT include pre-forward-start data (hard filter on start date from the
              Contract; assert every record ts >= start or drop with a logged count).
        - [ ] Prints the forward-test date range prominently at the top.
        - [ ] Exports to Markdown AND JSON.
        - [ ] Generated by one CLI command.
        - [ ] Optionally sendable via Telegram (reuse `tools/tg_send.py` `tg_send_document`).
    - Notes: Content: equity curve since start, drawdown since start, rebalance count, avg/max/
      min exposure, v5-vs-v6-vs-legacy divergence, downtime incidents, missed heartbeats, data
      gaps (from Section 7), execution anomalies, reporting anomalies, decisions made, decisions
      skipped (needs T5.2 for full skip data; until then, report "skips: n/a until decision
      trace enabled"), simulated fees/slippage.

---

## 7. Data Integrity and Exchange Comparison

Make sure the data source is not silently corrupting the experiment.

- [x] **T7.1 — `okx-trader data-audit` for recent paper-trading data**
    - Priority:            P0
    - Status:              Done (2026-07-06; `tools/data_audit.py` + CLI. FOUND 474 dup rows — see Progress log)
    - Forward-test safe:   YES (data-integrity; read-only, never mutates cache)
    - Risk:                Low
    - Depends on:          none
    - Files likely involved: new `tools/data_audit.py` + CLI reg; reuse `data/ohlcv_cache.py`,
      `tools/report_common.py` (`cache_bounds`), existing `audit-backtest` skill logic,
      `strategies/indicators.py` timestamp conventions.
    - Acceptance criteria:
        - [ ] A command audits recent paper-trading candles.
        - [ ] Detects missing / stale / duplicated candles.
        - [ ] Detects OHLCV outliers and timezone inconsistencies (UTC invariant).
        - [ ] Classifies OKX API errors seen in logs.
        - [ ] Read-only; never re-downloads or rewrites `data/cache/` (respects the 2026-07-06
              cache-mutation incident lesson in CLAUDE.md — tools CLAMP, never extend).
    - Notes: This overlaps the existing `audit-backtest` skill and `tools/strategy_audit.py`;
      reuse, don't reimplement.

- [ ] **T7.2 — Cross-exchange OHLCV comparison (research/audit-only)**
    - Priority:            P3
    - Status:              Parked
    - Forward-test safe:   YES (data-integrity, read-only) — but MUST NOT replace canonical data
    - Risk:                Medium
    - Depends on:          T7.1
    - Files likely involved: new `tools/exchange_compare.py`; HTTP via `urllib.request`/`aiohttp`
      (NEVER `requests` — CLAUDE.md); compares OKX vs Binance/Coinbase/Kraken.
    - Acceptance criteria:
        - [ ] Compares OKX vs >=1 other exchange OHLCV for a window.
        - [ ] Flags where signal decisions WOULD change under alternate data (offline recompute
              of regime/phase only — no live effect).
        - [ ] Explicitly labeled research/audit-only in output + docstring.
        - [ ] Does NOT replace the canonical source without explicit written approval.
    - Notes: Canonical dataset is sacred (102931-candle `BTC-USDT_1H`, versioned in git).

---

## 8. Conservative Paper Execution Mode

Current live paper fills may be too clean. Add a pessimistic simulation mode for FUTURE paper
tests — without touching the frozen strategy or the running bots.

- [ ] **T8.1 — `paper_conservative` execution profile in the paper client**
    - Priority:            P2
    - Status:              Not started
    - Forward-test safe:   NO (changes execution behavior) — apply to a NEW/non-participating
      paper instance only; must NOT be switched on for the 3 bots mid-test.
    - Risk:                Medium
    - Depends on:          T3 (contract must authorize a new instance), T7.1
    - Files likely involved: `core/exchange.py` (paper fill path) and/or `core/backtest.py`
      cost-mode machinery (already has `ideal`/`realistic`/`conservative`/`bybit` modes,
      lines 31-40); `config/settings.py` for an opt-in profile; NEVER `strategies/`.
    - Acceptance criteria:
        - [ ] Basic paper vs conservative paper can be compared side by side.
        - [ ] Conservative mode does NOT modify frozen strategy code.
        - [ ] Differences reported clearly (reuse Section 6 report).
        - [ ] Reusable in future paper tests.
        - [ ] Assumptions documented (in `DEPLOY_PAPER.md` + the mode's docstring).
    - Notes: Simulate worse fill price, dynamic slippage, spread, execution delay
      (one-candle-delayed fill), partial/no-fill, API downtime, higher fees. Reuse the existing
      cost-mode enum rather than inventing a parallel system. Running it against the live 3 bots
      would break comparability — spin up a 4th `instance_id` instead.

---

## 9. Robustness and Stress Lab

Test how fragile the FROZEN strategy is under worse assumptions — as VALIDATION, never to tune.

- [ ] **T9.1 — Stress harness over existing backtest engine**
    - Priority:            P2
    - Status:              Not started
    - Forward-test safe:   YES (safe-infra; historical backtests, no live effect)
    - Risk:                Low
    - Depends on:          none
    - Files likely involved: new `tools/stress_lab.py`; reuse `core/backtest.py` cost modes,
      `cli/backtest_cmds.py` (`sensitivity`, `walk-forward`), `tools/swing_rolling_start_matrix.py`,
      `tools/degradation_report.py`, `tools/stress_usdt_depeg.py` (already exists), `report_common`.
    - Acceptance criteria:
        - [ ] Labeled as VALIDATION, not optimization (banner in output + docstring).
        - [ ] Each report states whether the test is forward-safe.
        - [ ] Reuses existing backtest/audit architecture (no new engine).
        - [ ] Results exportable (Markdown/CSV/JSON via `report_common`).
    - Notes: Scenarios: doubled slippage, tripled fees, delayed execution, data gaps, missing
      external-context (`disable_external_filters` already exists for ablation), API downtime,
      random-window (`random-backtest` exists), Monte Carlo sequence perturbation (if feasible),
      worst historical periods — 2018 bear, Mar-2020 crash, 2021 top, 2022 bear, post-ETF 2024,
      halving-cycle boundaries. **Results MUST NOT feed parameter changes (Section 2 rule 5).**

---

## 10. Replay Visualizer

Visually inspect backtest/forward behavior over time to catch absurd decisions hidden by
aggregate metrics.

- [ ] **T10.1 — Static HTML/PNG replay of a run**
    - Priority:            P2
    - Status:              Not started
    - Forward-test safe:   YES (observability, read-only)
    - Risk:                Low
    - Depends on:          T5.1 (decision reasons), T6.1 (forward slice)
    - Files likely involved: extend `tools/swing_chart.py` (+ `swing_chart_template.html`) which
      already charts swing runs; `matplotlib` (already a dep for `/equity`, `tools/tg_charts.py`);
      reads swing journals + `swing_rebalances.jsonl`.
    - Acceptance criteria:
        - [ ] Inspect a selected date range.
        - [ ] Focus on specific crisis windows.
        - [ ] Read-only (no order path, no strategy import for mutation).
        - [ ] Helps detect absurd decisions hidden by aggregate metrics.
    - Notes: **Recommendation: static HTML + matplotlib PNG export, reusing `swing_chart.py`
      and the existing `*_template.html` pattern.** No Streamlit/Plotly server for now (same
      rationale as Section 4). Show: BTC price, equity, BTC/cash alloc, rebalance points,
      drawdowns, bull/bear regime, halving phase, decisions, skipped decisions (needs T5.2),
      key external-context values.

---

## 11. Experiment Registry

Track every research experiment + decision so failed ideas are not silently repeated.

- [ ] **T11.1 — `EXPERIMENTS.md` registry (+ optional JSONL mirror)**
    - Priority:            P1
    - Status:              Not started
    - Forward-test safe:   YES (docs)
    - Risk:                Low
    - Depends on:          none
    - Files likely involved: new `EXPERIMENTS.md`; optionally `data/runtime/experiments.jsonl`;
      seed from existing "Descartado y NO reintentar" lists in `SESSION.md` +
      `backtests/STRATEGY_VERSIONS.md` + `AUDITORIA_SWING_*.md`.
    - Acceptance criteria:
        - [ ] New experiments logged consistently (template block below).
        - [ ] Rejected ideas easy to find (a "Rejected — do not retry" section).
        - [ ] Prevents accidental repeats of the same failed idea.
        - [ ] Supports future portfolio/documentation use.
    - Notes: Per experiment: id, title, hypothesis, strategy affected, date, branch/commit,
      data window, metrics, result, decision (accepted/rejected/parked), reason, allowed-during-
      forward-test? (yes/no), related journal/report paths. **Recommendation: Markdown primary**
      (this repo is doc-heavy and single-user; SQLite is overkill). Migrate the already-scattered
      "Descartado" knowledge here so it stops living in prose.

---

## 12. Journal Query System

A query layer over backtest + paper journals so huge JSON never gets loaded by hand.

- [ ] **T12.1 — `okx-trader journal-query` CLI over rebalance/trade records**
    - Priority:            P1
    - Status:              Not started
    - Forward-test safe:   YES (observability, read-only)
    - Risk:                Low
    - Depends on:          none
    - Files likely involved: new `tools/journal_query.py` + CLI reg; reuse
      `tools/journal_summary.py` (already the token-safe summarizer), `core/database.py`
      (`Trade` is already SQL-backed — prefer SQL there), `swing_rebalances.jsonl`,
      swing journals; honor `.claude/hooks/read_guard.py` (never Read raw >10MB journals).
    - Acceptance criteria:
        - [ ] Does not require loading huge journal files manually.
        - [ ] CLI commands answer the canned questions.
        - [ ] Concise output.
        - [ ] Exports Markdown/CSV/JSON where useful.
    - Notes: Queries: worst/best rebalances, inspect date X, compare v5/v6 around date X, all
      allocation changes > N%, periods at 100% exposure during drawdown, decisions during
      Mar-2020, decisions around halvings, all skipped rebalances (skips need T5.2). **Prefer
      SQL for `trades` (already persisted); use a safe JSONL parser for `swing_rebalances.jsonl`
      and file journals.**

---

## 13. Anomaly and Red-Flag System

Warn when something is wrong/suspicious. **Never auto-changes strategy.**

- [x] **T13.1 — Anomaly checker feeding CLI/dashboard + critical Telegram alerts**
    - Priority:            P0
    - Status:              Done (2026-07-06; `tools/anomaly_check.py` + CLI `--telegram`, dedup TTL)
    - Forward-test safe:   YES (observability; read-only detection + alert send only)
    - Risk:                Low
    - Depends on:          T4.2 (snapshot), T7.1 (data checks)
    - Files likely involved: new `tools/anomaly_check.py`; reuse `tools/tg_send.py`,
      `tools/telegram_remote.py` (heartbeat/watchdog already there), `daily_checks.sh`,
      `tg_state.json`, `core/database.py`, `swing_rebalances.jsonl`,
      `tools/audit_equity_recon.py` (equity reconciliation already exists).
    - Acceptance criteria:
        - [ ] Alerts appear in CLI/dashboard.
        - [ ] Critical alerts can go to Telegram.
        - [ ] Alerts deduplicated (reuse the dedup pattern already in `telegram_remote`/`tg_state`).
        - [ ] Each alert has severity + suggested action.
        - [ ] Alerts NEVER trigger an automatic strategy change (detection only).
    - Notes: Red flags: missing heartbeat, stale market data, missing candles, bot process
      stopped, Telegram unresponsive, OKX connection fail, DB write fail, exposure != target
      unexpectedly, v6 diverges from v5 before ~2026-10-07 (a strong red flag — should be
      impossible), equity reconciliation mismatch (`audit_equity_recon.py`), drawdown beyond
      expected range (per Contract), too many skipped decisions, impossible allocation
      (outside [min_btc_pct, max_btc_pct]), invalid cash/BTC balance, repeated API failures.

---

## 14. Personal Portfolio Allocator Simulator

Personal what-if tool for real-world allocation questions. Low priority; only if clearly safe.

- [ ] **T14.1 — Read-only allocation simulator (research tooling, NOT advice)**
    - Priority:            P3
    - Status:              Parked
    - Forward-test safe:   YES (safe-infra; pure simulation, no live/paper coupling)
    - Risk:                Low
    - Depends on:          T9.1 (reuse historical scenarios)
    - Files likely involved: new `tools/portfolio_sim.py`; reuse `core/backtest.py` engine +
      `reporting/fiscal_report.py` (tax approximation already exists); NO import of live client.
    - Acceptance criteria:
        - [ ] Separated from live/paper execution (cannot import an order path).
        - [ ] Cannot place orders (no client instantiation).
        - [ ] Read-only simulations only.
        - [ ] Assumptions documented; output carries a "not financial advice" banner.
    - Notes: Simulate initial capital, monthly contributions, DCA vs lump sum, alloc under the
      swing strategy, tax approximation (via `fiscal_report`), drawdown scenarios, bull/bear
      start timing, expected rebalance frequency, worst-case historical start dates.

---

## 15. Portfolio / Public Demo Preparation

Make the project presentable as a serious engineering artifact — honest about limitations.

- [ ] **T15.1 — README + demo packaging rewrite**
    - Priority:            P1
    - Status:              Not started
    - Forward-test safe:   YES (docs)
    - Risk:                Low
    - Depends on:          T4.1, T6.1, T10.1 (for screenshots/sample outputs)
    - Files likely involved: `README.md` (501 lines today), `.env.example` (exists), new
      `docs/` for architecture diagram + screenshots, `AGENTS.md`.
    - Acceptance criteria:
        - [ ] A recruiter/engineer understands the project in ~3 minutes.
        - [ ] README honest about limitations (dedicated section).
        - [ ] No live keys/secrets exposed (audit `.env.example` stays example-only; scan repo).
        - [ ] Results framed as research, not promised performance.
    - Notes: Include: improved README, architecture diagram (BacktestClient/OKXClient
      abstraction is the headline), screenshots, sample dashboard (Section 4) + sample reports
      (Section 6), anti-lookahead design writeup, paper/live separation, overfitting controls,
      synthetic/anonymized data if needed, GitHub cleanup, setup instructions, `.env.example`,
      demo commands, limitations section.
      **Positioning:** NOT "bot that makes 85% CAGR." USE: *"Bias-resistant BTC allocation
      research lab with backtesting, paper execution, audit tooling and forward-test
      monitoring."* Any CAGR shown MUST appear with max drawdown + cost assumptions + window.

---

## 16. Legal / Risk / Product Boundary

- [ ] **T16.1 — Limitations / risk / boundary section in docs**
    - Priority:            P1
    - Status:              Not started
    - Forward-test safe:   YES (docs)
    - Risk:                Low
    - Depends on:          none
    - Files likely involved: `README.md`, new `LIMITATIONS.md` (or a README section).
    - Acceptance criteria:
        - [ ] Docs include a limitations/risk section.
        - [ ] Public-facing wording avoids financial advice.
        - [ ] Tool stays framed as research software.
    - Notes: Mark as PREMATURE / out of scope: selling signals, investment advice, commercial
      product, accepting user funds, copy-trading for others, claiming expected returns, showing
      CAGR without drawdown+assumptions, marketing as a "money-making bot."

---

## 17. Suggested Implementation Order (phased)

Each phase lists its tasks, and the aggregate priority/risk/forward-safety/complexity.

### Phase 0 — Repository audit
- Tasks: (this document IS the deliverable) inspect structure, identify existing modules, map
  where each feature fits, mark safe vs dangerous areas.
- Priority: P0 | Risk: Low | Forward-safe: YES (read-only) | Complexity: Low
- Acceptance: this plan exists, every feature is mapped to a real module, dangerous areas flagged.
- Files inspected: `main.py`, `cli/*`, `strategies/*`, `core/*`, `data/*`, `reporting/*`,
  `tools/*`, `deploy/*`, `config/*`, `tests/*`, root `*.md`.
- STATUS: **Done** (this document).

### Phase 1 — Forward-test discipline
- Tasks: T3.1.
- Priority: P0 | Risk: Low | Forward-safe: YES | Complexity: Low
- Acceptance: Contract exists; frozen boundaries, intervention rules, metrics, failure
  conditions all written and citable.
- Inspect/modify: `SESSION.md`, `DEPLOY_PAPER.md`, `SWING_V6_PLAN.md`, `data/runtime/`.

### Phase 2 — Observability
- Tasks: T6.1, T13.1, T5.1 (and T5.2 only after isolation review).
- Priority: P0-P1 | Risk: Low (T5.2 Medium) | Forward-safe: YES (T5.2 YES-if-isolated) |
  Complexity: Medium
- Acceptance: forward-only report, anomaly/heartbeat checks, decision explanation for executed
  rebalances all working read-only.
- Inspect/modify: `cli/report_cmds.py`, `tools/report_common.py`, `tools/tg_send.py`,
  `tools/telegram_remote.py`, `core/database.py`, `data/runtime/*`.

### Phase 3 — Dashboard
- Tasks: T4.1, T4.2.
- Priority: P0-P1 | Risk: Low | Forward-safe: YES | Complexity: Medium
- Acceptance: one command launches a Rich control center showing all 3 bots + stale/error states.
- Decision: extend Rich/`tg_views`, no web stack yet.
- Inspect/modify: new `cli/paper_cmds.py`, `main.py`, `tools/paper_bots.py`, `tools/tg_views.py`,
  `reporting/dashboard.py`.

### Phase 4 — Data and execution validation
- Tasks: T7.1, T8.1, T7.2.
- Priority: P0 (T7.1) to P3 (T7.2) | Risk: Low-Medium | Forward-safe: T7 YES, **T8.1 NO**
  (new instance only) | Complexity: Medium
- Acceptance: data-audit command, conservative paper profile (off the live bots), exchange
  comparison research-only.
- Inspect/modify: `data/ohlcv_cache.py`, `core/backtest.py` cost modes, `core/exchange.py`
  paper path, `config/settings.py`.

### Phase 5 — Research tooling
- Tasks: T9.1, T10.1, T12.1, T11.1.
- Priority: P1-P2 | Risk: Low | Forward-safe: YES | Complexity: Medium
- Acceptance: stress lab (validation-labeled), replay visualizer, journal query, experiment
  registry — all reusing existing backtest/audit/journal architecture.
- Inspect/modify: `tools/stress_lab.py`, `tools/swing_chart.py`, `tools/journal_query.py`,
  `EXPERIMENTS.md`, `cli/backtest_cmds.py`.

### Phase 6 — Portfolio packaging
- Tasks: T15.1, T16.1, T14.1 (parked).
- Priority: P1 (P3 for T14) | Risk: Low | Forward-safe: YES | Complexity: Low-Medium
- Acceptance: README understandable in 3 min, honest limitations, no secrets, research framing.
- Inspect/modify: `README.md`, `.env.example`, new `docs/`, `LIMITATIONS.md`.

---

## 18. Tracking Format (reference)

Statuses: `Not started` | `In progress` | `Blocked` | `Done` | `Rejected` | `Parked`.
Priorities: `P0` (do first) .. `P3` (nice-to-have). Use the task block from Section 0.
Update `Status:` in place as work proceeds; log rejected ideas into `EXPERIMENTS.md` (T11.1)
rather than deleting them.

---

## 19. Contamination watch (read before touching code)

Tasks that COULD contaminate the forward test if done carelessly:

- **T5.2 (skipped-decision trace)** — the only task that edits `strategies/swing_allocator.py`.
  Safe ONLY as additive, default-OFF logging verified byte-identical. Any behavior delta -> stop.
- **T8.1 (conservative paper mode)** — changes execution; must run on a NEW `instance_id`,
  never flipped on for the 3 live bots mid-test.
- **T7.2 / T9.1 results** — must NEVER feed a parameter change (Section 2 rule 5). Validation only.
- **Any cache tooling (T7.1)** — read-only; never re-download or extend `data/cache/` (repeat of
  the 2026-07-06 mutation incident would invalidate determinism).

Everything else in this plan is read-only observability, docs, or new isolated files and is
forward-test safe.
