# V8 X-Perp Demo: synthetic-cycle pull and operator runbook

This is an operator runbook, not deployment authorization. It keeps Live disabled, the hard Demo
cap at USD 1,000, and V7 as a historical replay control. Run these commands on the VM only after
reviewing the commit and choosing a future UTC anchor.

## 1. Pull the reviewed branch

```bash
cd /srv/matibot
git status --short --branch
git fetch origin codex/v8-xperp-intent-recovery
git pull --ff-only origin codex/v8-xperp-intent-recovery
git rev-parse HEAD
```

## 2. Disable legacy processes before installing V8

```bash
sudo systemctl disable --now \
  matibot.service \
  matibot-telegram.service \
  matibot-v7-paper.service \
  matibot-v7-shadow.service \
  matibot-v7-promotion.service \
  matibot-v7-certified-okx-demo.service 2>/dev/null || true
sudo systemctl list-units --type=service --state=running | grep -E 'matibot|telegram' || true
pgrep -af 'telegram_remote|v7_telegram|v8_xperp|main.py' || true
```

The last two commands must show no trading or Telegram process before continuing.

## 3. Create the protected V8 environment file

```bash
sudo install -d -m 0750 -o root -g root /etc/matibot
sudo install -m 0600 -o root -g root /dev/null /etc/matibot/v8-xperp-demo.env
sudoedit /etc/matibot/v8-xperp-demo.env
```

Use dedicated OKX Demo and Telegram credentials. Choose an anchor at least several minutes in the
future. Start with `real_cycle` while persisting the anchor and mode switch offline:

```dotenv
OKX_XPERP_DEMO_API_KEY=REPLACE_DEMO_ONLY
OKX_XPERP_DEMO_SECRET_KEY=REPLACE_DEMO_ONLY
OKX_XPERP_DEMO_PASSPHRASE=REPLACE_DEMO_ONLY
V8_LIVE_EXECUTION_ENABLED=false
V8_XPERP_CONTINUOUS_DEMO_ENABLED=true
V8_XPERP_MAX_NOTIONAL_USD=1000
V8_XPERP_DAILY_LOSS_USD=25
V8_XPERP_TOTAL_LOSS_USD=100
V8_XPERP_MIN_LIQ_DISTANCE_PCT=35
V8_XPERP_MAX_SPREAD_BPS=20
V8_XPERP_MAX_SLIPPAGE_BPS=15
V8_XPERP_MAX_MARKET_AGE_SECONDS=5
V8_XPERP_MAX_STREAM_AGE_SECONDS=15
V8_XPERP_MAX_CLOCK_DRIFT_SECONDS=2
V8_XPERP_MAX_API_FAILURES=3
V8_XPERP_MAX_RECONCILIATION_SECONDS=30
V8_XPERP_CYCLE_SECONDS=10
V8_BOOTSTRAP_MAX_EQUITY_LOSS_TO_REFERENCE_PCT=0.20
V8_BOOTSTRAP_MAX_LEVERAGE=2
V8_BOOTSTRAP_MIN_ENTRY_LEVERAGE=0.25
V8_BOOTSTRAP_OPERATIONAL_RESERVE_USD=5
V8_SCHEDULE_MODE=real_cycle
V8_SYNTHETIC_DEMO_CYCLE_ENABLED=true
V8_SYNTHETIC_CYCLE_ANCHOR_UTC=2030-01-01T00:00:00+00:00
V8_TELEGRAM_ENABLED=true
V8_TELEGRAM_BOT_TOKEN=REPLACE_DEDICATED_V8_TOKEN
V8_TELEGRAM_ALLOWED_CHAT_IDS=REPLACE_NUMERIC_CHAT_ID
V8_TELEGRAM_CONFIRMATION_SECONDS=120
```

Never put this file in Git or print it. Confirm permissions without displaying contents:

```bash
sudo stat -c '%a %U:%G %n' /etc/matibot/v8-xperp-demo.env
```

## 4. Install both V8 units inactive

```bash
cd /srv/matibot
sudo bash deploy/install_v8_xperp_demo.sh \
  /srv/matibot /etc/matibot/v8-xperp-demo.env matibot
sudo systemctl is-enabled matibot-v8-xperp-demo.service
sudo systemctl is-enabled matibot-v8-xperp-telegram.service
```

Both results must be `disabled`.

## 5. Persist the future anchor and synthetic mode while stopped

Replace the timestamp below with exactly the timestamp in the environment file:

```bash
cd /srv/matibot
set -a
source /etc/matibot/v8-xperp-demo.env
set +a
.venv/bin/python tools/v8_xperp_demo.py final-reconcile
.venv/bin/python tools/v8_xperp_demo.py graceful-shutdown
.venv/bin/python tools/v8_xperp_demo.py set-synthetic-anchor \
  2030-01-01T00:00:00+00:00 \
  --acknowledge 'future UTC anchor reviewed while service stopped' \
  --confirm-v8-synthetic-anchor
.venv/bin/python tools/v8_xperp_demo.py set-mode synthetic_demo_cycle \
  --acknowledge 'flat reconciled Demo account; enter isolated synthetic schedule' \
  --confirm-v8-schedule-mode
```

Now edit only this line:

```dotenv
V8_SCHEDULE_MODE=synthetic_demo_cycle
```

Reload the environment in the shell and preview three cycles. These commands submit no orders:

```bash
set -a
source /etc/matibot/v8-xperp-demo.env
set +a
.venv/bin/python tools/v8_xperp_demo.py schedule-mode-status
.venv/bin/python tools/v8_xperp_demo.py schedule-preview
.venv/bin/python tools/v8_xperp_demo.py synthetic-dry-run --cycles 3
.venv/bin/python tools/v8_xperp_demo.py preactivation
```

Preactivation must report `execute: false`, `schedule_mode: synthetic_demo_cycle`, a Demo
environment, zero unknown orders/intents, and a target no larger than USD 1,000.

## 6. Start only V8 and its dedicated Telegram companion

```bash
sudo systemctl enable --now matibot-v8-xperp-demo.service
sudo systemctl enable --now matibot-v8-xperp-telegram.service
sudo systemctl status --no-pager matibot-v8-xperp-demo.service
sudo systemctl status --no-pager matibot-v8-xperp-telegram.service
sudo journalctl -u matibot-v8-xperp-demo.service -n 100 --no-pager
sudo journalctl -u matibot-v8-xperp-telegram.service -n 100 --no-pager
sudo systemctl list-units --type=service --state=running | grep -E 'matibot|telegram'
pgrep -af 'v8_xperp|telegram_remote|v7_telegram|main.py'
```

Only `matibot-v8-xperp-demo` and `matibot-v8-xperp-telegram` may remain. The Telegram companion
has an independent restart policy; its outage does not stop healthy V8 execution.

## 7. Verify Telegram and the Day 2/Day 3 transitions

From the allowlisted chat:

```text
/help
/version
/status
/mode
/schedule
/next_transition
/position
/orders
/intents
/funding
/margin
/reconciliation
```

At Day 2 verify `/phase` reports `short_phase`, `/position` reports a capped short, `/orders`
reports zero, `/intents` reports zero non-terminal intents, and `/reconciliation` is healthy. At
Day 3 repeat those commands and require `long_phase` plus a capped long. Do not confirm a mutation
merely to acknowledge a scheduled transition; schedule transitions are executor-owned and their
reports are written automatically.

For a requested reconciliation:

```text
/reconcile
/confirm <nonce returned by the bot>
/reconciliation
```

## 8. Safe flatten and return to `real_cycle`

First request the normal persisted flat target:

```text
/flat
/confirm <nonce returned by the bot>
/position
/orders
/intents
/reconciliation
```

Require a flat position, zero orders, zero non-terminal intents, and healthy reconciliation. Then:

```bash
sudo systemctl stop matibot-v8-xperp-demo.service
sudo systemctl stop matibot-v8-xperp-telegram.service
cd /srv/matibot
set -a
source /etc/matibot/v8-xperp-demo.env
set +a
.venv/bin/python tools/v8_xperp_demo.py final-reconcile
.venv/bin/python tools/v8_xperp_demo.py set-mode real_cycle \
  --acknowledge 'synthetic state archived; flat reconciled account; return to real schedule' \
  --confirm-v8-schedule-mode
sudoedit /etc/matibot/v8-xperp-demo.env
```

Set:

```dotenv
V8_SCHEDULE_MODE=real_cycle
V8_SYNTHETIC_DEMO_CYCLE_ENABLED=false
```

Then preview and preflight before restarting:

```bash
set -a
source /etc/matibot/v8-xperp-demo.env
set +a
.venv/bin/python tools/v8_xperp_demo.py schedule-mode-status
.venv/bin/python tools/v8_xperp_demo.py preactivation
sudo systemctl start matibot-v8-xperp-demo.service
sudo systemctl start matibot-v8-xperp-telegram.service
sudo systemctl status --no-pager matibot-v8-xperp-demo.service
sudo journalctl -u matibot-v8-xperp-demo.service -n 100 --no-pager
```

Never transfer a synthetic position into real-cycle ownership. If normal flatten cannot prove
flat, stop and use the separately reviewed emergency procedure in
`docs/ops/v8-xperp-emergency-flatten.md`; do not switch modes while exposure or unresolved intents
remain.
