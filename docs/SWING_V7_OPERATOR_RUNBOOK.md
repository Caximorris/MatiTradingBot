# Swing v7 operator runbook

Use `python tools/v7_operator.py status --instance v7_btc_usdt_shadow` for read-only status and `diagnose` for the same redacted evidence. For a lock: first run `reconcile --instance ...` (dry-run), then `reconcile --paper --instance ...`; it writes an append-only audit record and submits zero orders. Only then may `unlock --instance ... --after-reconciliation <audit_id>` clear a lock. Blind unlock is rejected.

Daily comparison: `python tools/v7_daily_report.py`. Promotion evidence: `python tools/v7_promotion_controller.py --promote`. The controller will not promote early; inspect `data/runtime/v7/promotion_report.json` for missing gates.

Alerts are surfaced by the existing `anomaly-check` for service/wallet/staleness failures. V7-specific controller reports should be included in the existing Telegram/ops alert route before production activation; they never alter targets.
