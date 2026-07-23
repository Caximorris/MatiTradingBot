# MatiTradingBot agent contract

Python 3.12/3.13 on Windows PowerShell. Read this file and `SESSION.md` before edits. `SESSION.md`
is a short live-state index; consult linked documents only when relevant. Do not read raw journals;
use `python tools/journal_summary.py <path>`.

## Work style

- Inspect `git status`, the target, direct tests, and consumers before editing.
- Make the smallest reversible change. Use `Decimal` for money, UTC in persistence, `loguru` for
  logs, `aiohttp` or `urllib.request` for HTTP, and add indicators only to `strategies/indicators.py`.
- State evidence as `[Certain]`, `[Likely]`, or `[Guessing]`. Do not call work complete without
  reviewing `git diff --check`, the full diff, status, and relevant validation output.
- Recommend Luna for mechanical/docs work, Terra for normal multi-file implementation, and Sol for
  architecture, security, execution, deployment, ambiguous failures, or broad audits. Routing is
  advisory: do not stop or create a handoff solely because a higher model is recommended.

## Boundaries

- Interface (`main.py`, `cli/`, Telegram, reports) delegates; strategy rules belong in `strategies/`.
  `core/` owns contracts/backtest/execution; strategies must work through the common client contract.
- No `requests`, embedded secrets, direct SQL edits to runtime state, canonical-cache rewrites,
  journal rewrites, or edits to `.env`, DBs, wallets, logs, `graphify-out/`, or generated evidence.
- Never run `start`, `stop`, `tools/paper_fleet_setup.py`, candidate setup/promotion tools, a live or
  demo order, Telegram mutation, VM/SSH action, deployment, push, merge, or release unless the user
  explicitly authorizes that action in the current request.
- Do not weaken authentication, risk limits, fees, slippage, closed-bar rules, lookahead protections,
  or validation to obtain a green result. `allow_shorts=False` unless explicitly approved.
- `strategies/pro_trend.py`, frozen Swing v6-2 defaults, `core/exchange.py`, `core/okx_demo_client.py`,
  deployment/CI, and schema/risk changes require explicit approval and a rollback plan.

## Fast lane: isolated strategy to paper

The goal is `candidate ready for isolated paper`, not `default adopted`.

1. Record one hypothesis, mechanism, expected failure, rollback, and a finite backtest budget.
2. Implement an isolated `BaseStrategy` plus config (`from_dict`/`to_dict`), `StrategyMeta`, warmup,
   closed-bar behavior, and focused tests (config, state/entries/exits, client contract, rollback).
3. Run paired deterministic backtests with realistic costs; fix actual defects and rerun. Finalists also
   run conservative costs, lookahead/data checks, and the smallest anti-overfitting suite that can
   falsify the hypothesis (sensitivity/OOS or rolling starts, as appropriate). Do not tune on its test set.
4. Run focused tests, then `pytest`, `compileall`, `build`, and Ruff ratchet; review the diff. A valid
   result may be labelled `PAPER_CANDIDATE_READY` even when it is not proven profitable or adoptable.
5. Create a candidate-specific setup path modeled on `tools/v7_paper_setup.py`: unique instance,
   isolated wallet/portfolio/journal, inactive by default, `service_managed=True`, and no live/demo path.
   Do not add candidates to `paper_fleet_setup.py`; it reconciles only the frozen v6/demo control fleet.
6. Human approval is still required to execute the setup or activate paper. A VM pull/deploy is a
   separate explicit request. Roll back by deactivating the candidate, never deleting evidence/state.

Use specialists only when the user asks for broad research, an independent audit, a promotion decision,
or a material data/execution/risk question. Do not automatically spawn them for ordinary implementation
or to satisfy a hook. A strategy implementer may run the defined validation suite; independent review is
required before changing a frozen default, not before starting isolated paper.

## Promotion is a different decision

`PAPER_CANDIDATE_READY` does not change a default and does not authorize live trading. Default/live
promotion needs explicit user approval, paired reproducible evidence, independent review where data,
execution, risk, or robustness changed, and forward evidence when the historical sample is closed.
For Swing, use `mati-swing-validator` only for a default/promotion decision; v6-2 remains frozen and v5
is its rollback/control. See `docs/swing/v6-plan.md` and `docs/forward-test/contract.md`.

## Backtest invariants

- Deterministic cache inputs; same window means same candle count. Backtests are continuous.
- Higher-timeframe/current bars and external inputs must be closed and point-in-time available. Keep the
  existing lags: MVRV prior day, DXY/NDX/VIX prior session, funding prior complete day.
- Default backtest cost modes: ideal = 0.1%/0 bps, realistic = 0.1%/5 bps, conservative = 0.1%/15 bps.
- Compare paired runs on the same cache, window, warmup, configuration, and costs. Report what fits the
  strategy type; Swing comparisons also report `final_btc_qty`, `bnh_initial_btc`, and `btc_vs_bnh_ratio`.

## Validation and git

For code changes, run the relevant focused tests plus:

```powershell
python -m pytest -q
python -m compileall -q .
python -m build
python tools/ruff_ratchet.py
```

Keep pre-existing failures visible and distinguish them from the change. `python -m ruff check .` may
contain baseline debt; do not hide it. Check command help before relying on an unfamiliar CLI command.

Work on `codex/<topic>`, use atomic conventional commits, and never force-push, reset hard, clean the
worktree, or commit secrets, runtime state, canonical caches, raw journals, logs, or generated artifacts.
Creating a commit does not authorize push. If a required decision materially changes risk, scope, or
production behavior, stop and ask for it; otherwise proceed with the fast lane.

## Long-running tasks

Follow docs/codex/autonomous-continuation.md. Maintain .codex/TASK_STATE.md, resume the first
incomplete milestone, and do not end on a progress update while recoverable work remains.

## References on demand

- Current state: `SESSION.md`; historical record: `docs/archive/session-archive.md`.
- Candidate paper workflow: `docs/forward-test/candidate-paper-workflow.md`.
- Swing default/forward controls: `docs/swing/v6-plan.md`, `docs/forward-test/contract.md`.
- Architecture and research tools: `.codex/skills/quant-orchestrate-research/references/project-surface.md`.
- Run `python tools/context_pack.py strategy|backtest|paper` before broad repository exploration.
  Use Graphify only for an explicit multi-module architecture/map request, capped at 600 tokens by default.
- `python tools/instruction_budget.py` enforces the persistent-instruction budget. Keep project skills
  below 110 lines each and 1,100 lines total; move rare detail into referenced documents.
