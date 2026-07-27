# V6 to V7 shared OKX Demo cutover

The OKX Demo account is a single shared wallet: exactly one strategy owner may hold its append-only lease. V7 remains statistically fragile and not live-ready.

On the VM, first ensure the checkout is clean, then update it:

```bash
git status --short
git fetch origin
git rev-parse origin/main
git pull --ff-only origin main
git rev-parse HEAD
python -m pip install -e '.[dev]'
```

Read-only V6 audit: `python tools/v6_v7_demo_cutover.py audit-v6 > v6-audit.json`. Review `verdict`, `reasons`, `open_orders`, `balances`, and `audit_hash` with `python -m json.tool v6-audit.json`.

The current command deliberately returns `BLOCKED` until a complete V6 service/journal reconciliation implementation is reviewed. Do not stop V6, export its evidence, or activate V7 based on a non-PASS report.

When a later reviewed build provides those commands, the ordered operation is: audit V6 PASS; export V6 evidence; guarded V6 stop using the explicit audit hash; verify no V6 service/order/lease; create inactive V7; run V7 preflight; activate V7 with explicit acknowledgements; inspect the V7 daily report. Every persistent or service-changing command requires a new explicit authorization.
