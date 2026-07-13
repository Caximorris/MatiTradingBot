# FORWARD_TEST_CONTRACT.md

> **Locked rules of the live paper forward test.** Written BEFORE reading more results so
> nothing can be reinterpreted after the fact. If you want to change a rule here, do it in a
> commit dated BEFORE the observation it would affect — never retroactively.
>
> Canonical companion to `SESSION.md` (state) and `DEPLOY_PAPER.md` (ops). Tracked by
> `FORWARD_TEST_AND_RESEARCH_LAB_PLAN.md` task T3.1.
>
> **Machine-readable mirror:** the single source of truth for the start date consumed by
> tooling is the constant `FORWARD_TEST_START` in `tools/forward_report.py`. It MUST equal the
> date in section 1 below. If you change one, change the other in the same commit.

---

## 1. Test identity

| Field | Value |
|-------|-------|
| **Forward-test start date** | **2026-07-04** (UTC) — paper deploy on the GCP VM (`DEPLOY_PAPER.md`) |
| **Per-wallet baseline** | the `INIT` record in `data/runtime/swing_rebalances.jsonl` for each bot is the authoritative baseline for THAT wallet. Reconcile against the start date; if a wallet's INIT is later than 2026-07-04, that wallet's clock starts at its INIT. |
| **Minimum observation period** | 90 days from start for v5/legacy execution-stability sign-off (F13/F15/F19). For any **v6-vs-v5 strategy** judgment: minimum 90 days AFTER first expected divergence (~2026-10-07), i.e. not before ~2027-01-05. |
| **Evaluation date (first)** | 2026-10-04 (execution stability + data integrity review). **No strategy verdict before this.** |
| **v6-vs-v5 evaluation date** | not before ~2027-01-05 (see minimum observation period). |

## 2. Variants under test

| Label | Bot (`BotState.strategy_name`) | Wallet file | Notes |
|-------|-------------------------------|-------------|-------|
| **v5** | `swing_allocator_v5_*` | `data/runtime/paper_state_<id>.json` | Frozen default at test start; now rollback/control. Tag `swing-v5-frozen`. |
| **v6** | `swing_allocator_v6_*` | `data/runtime/paper_state_<id>.json` | Current frozen default: phase router + funding overlay. **Expected to be byte-identical to v5 until ~2026-10-07** (still in `bear_onset`; overlay only fires in `accumulation`). |
| **legacy** | `swing_allocator_*` (no version) | shared `data/runtime/paper_state.json` | Pre-isolation bot. Kept for continuity. |

**Amendment 2026-07-13:** v6-2 became the code/default-paper configuration by explicit user
decision after paired validation. The original labels and start-date rules above remain locked:
v5 is now the rollback/control, v6 is the default, and no live authorization is implied.

Wallets are ISOLATED per `instance_id` / `paper_portfolio_id`. Never share or reset a wallet
mid-test.

## 3. Allowed interventions (do NOT invalidate results)

- Restart the VM, the `matibot` service, or the `matibot-telegram` service.
- Fix / deploy **observability, reporting, data-integrity, or docs** code (plan classes
  `observability` / `data-integrity` / `docs` / `safe-infra`).
- Restore `data/cache/BTC-USDT_1H.json` from git if a tool mutated it.
- Pause/resume a bot via `is_active` (the existing `bot enable/disable` / Telegram `/pause`
  flip) — this does not change strategy logic. Log the reason.
- Rotate secrets, change Telegram chat, adjust logging levels.

## 4. Forbidden interventions (INVALIDATE results if done)

- Edit strategy code, parameters, signals, deltas, thresholds, or allocation rules
  (`strategies/swing_allocator.py` decision path and its config defaults).
- Tune ANY parameter using forward/paper data.
- Adopt or reject a variant based on a single event (one rebalance, one drawdown spike).
- Delete, truncate, or rewrite existing journals / `swing_rebalances.jsonl` / wallet files.
- Reset a wallet, change `initial_balance`, or swap `instance_id` mid-test.
- Switch the canonical data source, or let a tool re-download / extend the OHLCV cache
  (regla 4, determinismo). Tools must CLAMP to `report_common.cache_bounds` and never write.
- Turn on `paper_conservative` execution (plan T8.1) for the 3 live bots. Use a NEW 4th wallet.

## 5. Metrics tracked (definitions locked)

Computed forward-only (records with `ts >= FORWARD_TEST_START`). Sources are existing
persistence — no new strategy state.

- **Equity** = `BTC_qty * spot + USDT`, per wallet (`paper_state_<id>.json` + OKX spot ticker).
- **Drawdown** = `(equity - running_peak) / running_peak`, running peak since start.
- **Rebalance count** = rows in `swing_rebalances.jsonl` for that bot with `ts >= start`.
- **Exposure** = `BTC_value / equity` (avg / max / min over the window).
- **bot/B&H ratio** = anchor metric (`_perf_ratio`): bot return / BTC buy-and-hold return
  since the wallet's INIT. `< 1.0` = holding less BTC than B&H.
- **v5/v6/legacy divergence** = difference in target/actual allocation and equity between bots.
- **Uptime / missed heartbeats** = from `daily_checks.log` + `tg_state.json`.
- **Data gaps** = `ohlcv_cache.contiguity_report` on the window (gaps > 3 bars).

## 6. Failure taxonomy (the point of this document)

A result only counts against the STRATEGY if it is NOT explained by infrastructure.

### 6a. Real forward-test failure (counts against the strategy)
The strategy behaved exactly as designed (verified: correct signals, no lookahead, inputs
available) AND the outcome breaches a pre-declared bound over the minimum window. Examples:
- Realized max drawdown materially worse than the backtest envelope (v5 anchor ~-52.7%) for a
  comparable regime, sustained, with clean execution.
- bot/B&H ratio persistently and structurally below backtest expectation across the window.
- v6 underperforms v5 over a full post-divergence window with clean execution on both.

### 6b. Infrastructure failure (does NOT count against the strategy; invalidates the window)
- Missed heartbeats / VM or service down / process crash.
- OKX API errors, rate limits, 403s, ticker outages.
- Missing / stale / duplicated candles feeding a decision.
- DB write failure; wallet-state corruption.
- Telegram / reporting failure (these NEVER affect trading, only visibility).
- Clock skew, timezone drift.

When 6b occurs: **log it, classify the affected window as invalid for strategy evaluation,
annotate it in the forward report's "infra incidents" section, and exclude that window from any
6a judgment.** Fix the infra, resume.

### 6c. Experiment invalidation (voids results from that point forward)
Any of these found mid-test voids results going forward and RESETS the observation clock:
- A lookahead leak discovered in the live path.
- A mutation of the canonical OHLCV cache.
- Any change to the frozen strategy path (even accidental).
- A wallet reset / balance edit.

Document the invalidation in `EXPERIMENTS.md` (plan T11.1) with the commit and date.

## 7. Incident handling playbook

| Event | Immediate action | Classification |
|-------|------------------|----------------|
| Missed heartbeat | check VM + services; restart if down | 6b infra |
| OKX API errors (repeated) | log, let the service retry (it retries indefinitely); annotate window | 6b infra |
| Missing candles at decision time | `data-audit` (plan T7.1); if a decision used a gap, mark that decision's window invalid | 6b infra + possible 6c |
| Telegram/reporting down | restart `matibot-telegram`; trading is unaffected | 6b infra (visibility only) |
| Downtime (VM off N hours) | record start/end; exclude window from 6a; strategy resumes from persisted wallet | 6b infra |
| v6 diverges from v5 BEFORE ~2026-10-07 | **red flag** — investigate immediately, likely a bug; do not treat as signal | 6c until explained |
| Equity reconciliation mismatch | `audit_equity_recon.py`; if state corrupted, 6c | 6b or 6c |

## 8. Acceptance criteria for this contract (plan T3.1)

- [x] Contract exists at repo root.
- [x] Human-readable; no code required to understand it.
- [x] Clearly separates strategy failure (6a) from infrastructure failure (6b).
- [x] Referenceable by future reports (they cite section numbers; start date mirrored in code).
- [x] Prevents post-hoc reinterpretation (locked start date, locked metric defs, locked taxonomy).

---

*Change log: append dated entries below. Never edit history above retroactively.*

- 2026-07-06 — Contract created (plan T3.1). Start date fixed at 2026-07-04.
