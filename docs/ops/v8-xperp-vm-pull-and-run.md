# V8 X-Perp Demo: VM pull and activation

This runbook is operator-executed. Codex does not connect to the VM. It affects
only the dedicated V8 OKX EEA Demo account and never authorizes Live.

## 1. Pull the reviewed branch

```bash
sudo systemctl status --no-pager matibot-v8-xperp-demo.service || true
sudo systemctl stop matibot-v8-xperp-demo.service || true
cd /srv/matibot
git status --short
git fetch origin codex/v8-xperp-intent-recovery
git switch codex/v8-xperp-intent-recovery
git pull --ff-only origin codex/v8-xperp-intent-recovery
git rev-parse HEAD
.venv/bin/python -m pip install -e .
```

Stop if `git status --short` shows VM-only edits that you have not preserved.

## 2. Create the root-only environment file

```bash
sudo install -d -m 0755 /etc/matibot
sudo install -m 0600 -o root -g root /dev/null /etc/matibot/v8-xperp-demo.env
sudoedit /etc/matibot/v8-xperp-demo.env
```

Enter the dedicated Demo credentials and the frozen limits:

```dotenv
OKX_XPERP_DEMO_API_KEY=REPLACE
OKX_XPERP_DEMO_SECRET_KEY=REPLACE
OKX_XPERP_DEMO_PASSPHRASE=REPLACE
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
V8_BOOTSTRAP_MAX_EQUITY_LOSS_TO_REFERENCE_PCT=0.20
V8_BOOTSTRAP_MAX_LEVERAGE=2
V8_BOOTSTRAP_MIN_ENTRY_LEVERAGE=0.25
V8_BOOTSTRAP_OPERATIONAL_RESERVE_USD=5
V8_XPERP_CYCLE_SECONDS=10
```

Do not reuse shared, V7, or Live credentials.

## 3. Install inactive and run no-order preactivation

Replace `matibot` only if the repository service user differs.

```bash
cd /srv/matibot
sudo bash deploy/install_v8_xperp_demo.sh /srv/matibot /etc/matibot/v8-xperp-demo.env matibot
sudo systemd-analyze verify /etc/systemd/system/matibot-v8-xperp-demo.service
sudo systemd-run --quiet --wait --pipe --collect --uid=matibot --property=WorkingDirectory=/srv/matibot --property=EnvironmentFile=/etc/matibot/v8-xperp-demo.env /srv/matibot/.venv/bin/python /srv/matibot/tools/v8_xperp_demo.py preactivation
```

The preactivation output must say `execute: false`, identify `okx_demo`, show
the `BTC-USD` index source, and remain at or below the USD 1,000 cap. Stop on
`BLOCKED`, an unknown position/order, a Live endpoint, or inconsistent source.

## 4. Activate

Activation can place one bounded OKX Demo order when the account is flat and
the frozen transport decision requires exposure.

```bash
sudo systemctl enable --now matibot-v8-xperp-demo.service
sudo systemctl status --no-pager matibot-v8-xperp-demo.service
sudo journalctl -u matibot-v8-xperp-demo.service -n 100 --no-pager
sudo -u matibot bash -lc 'cd /srv/matibot; .venv/bin/python tools/v8_xperp_demo.py health'
sudo -u matibot bash -lc 'cd /srv/matibot; .venv/bin/python tools/v8_xperp_demo.py operational-status'
```

## 5. Restart and exactly-once verification

```bash
sudo systemctl restart matibot-v8-xperp-demo.service
sleep 15
sudo systemctl status --no-pager matibot-v8-xperp-demo.service
sudo journalctl -u matibot-v8-xperp-demo.service --since '-2 minutes' --no-pager
sudo -u matibot bash -lc 'cd /srv/matibot; .venv/bin/python tools/v8_xperp_demo.py health'
```

The restart must report `ADOPT` for an unchanged known position and must not
create another opening intent. Inspect persisted identities with:

```bash
sudo systemd-run --quiet --wait --pipe --collect --uid=matibot --property=WorkingDirectory=/srv/matibot --property=EnvironmentFile=/etc/matibot/v8-xperp-demo.env /srv/matibot/.venv/bin/python /srv/matibot/tools/v8_xperp_demo.py list-intents
sudo systemd-run --quiet --wait --pipe --collect --uid=matibot --property=WorkingDirectory=/srv/matibot --property=EnvironmentFile=/etc/matibot/v8-xperp-demo.env /srv/matibot/.venv/bin/python /srv/matibot/tools/v8_xperp_demo.py funding-status
```

## 6. Routine operations

```bash
sudo systemctl start matibot-v8-xperp-demo.service
sudo systemctl stop matibot-v8-xperp-demo.service
sudo systemctl restart matibot-v8-xperp-demo.service
sudo systemctl status --no-pager matibot-v8-xperp-demo.service
sudo journalctl -u matibot-v8-xperp-demo.service -f
sudo systemd-run --quiet --wait --pipe --collect --uid=matibot --property=WorkingDirectory=/srv/matibot --property=EnvironmentFile=/etc/matibot/v8-xperp-demo.env /srv/matibot/.venv/bin/python /srv/matibot/tools/v8_xperp_demo.py preflight
sudo systemd-run --quiet --wait --pipe --collect --uid=matibot --property=WorkingDirectory=/srv/matibot --property=EnvironmentFile=/etc/matibot/v8-xperp-demo.env /srv/matibot/.venv/bin/python /srv/matibot/tools/v8_xperp_demo.py final-reconcile
```

Stop the unit before any direct authenticated recovery command so the
account-scoped process lock has exactly one owner.

## 7. Operator flat, emergency action, and manual recovery

Request a controlled flat transition while the service is running:

```bash
sudo -u matibot bash -lc 'cd /srv/matibot; .venv/bin/python tools/v8_xperp_demo.py operator-flat --confirm-v8-operator-flat'
```

For an emergency flatten, stop the service, reconcile, and run only the
explicit reduce-only emergency path:

```bash
sudo systemctl stop matibot-v8-xperp-demo.service
sudo systemd-run --quiet --wait --pipe --collect --uid=matibot --property=WorkingDirectory=/srv/matibot --property=EnvironmentFile=/etc/matibot/v8-xperp-demo.env /srv/matibot/.venv/bin/python /srv/matibot/tools/v8_xperp_demo.py startup-recovery
sudo systemd-run --quiet --wait --pipe --collect --uid=matibot --property=WorkingDirectory=/srv/matibot --property=EnvironmentFile=/etc/matibot/v8-xperp-demo.env /srv/matibot/.venv/bin/python /srv/matibot/tools/v8_xperp_demo.py flatten --confirm-v8-emergency-flatten
sudo systemd-run --quiet --wait --pipe --collect --uid=matibot --property=WorkingDirectory=/srv/matibot --property=EnvironmentFile=/etc/matibot/v8-xperp-demo.env /srv/matibot/.venv/bin/python /srv/matibot/tools/v8_xperp_demo.py final-reconcile
```

After investigating a manual-recovery latch, clear it only while flat with
zero FUTURES orders:

```bash
sudo systemd-run --quiet --wait --pipe --collect --uid=matibot --property=WorkingDirectory=/srv/matibot --property=EnvironmentFile=/etc/matibot/v8-xperp-demo.env /srv/matibot/.venv/bin/python /srv/matibot/tools/v8_xperp_demo.py manual-recovery --confirm-v8-manual-recovery
sudo systemctl reset-failed matibot-v8-xperp-demo.service
```

For rollback, preserve all runtime evidence, stop and disable the unit, then
return the checkout to the previous committed V8 checkpoint:

```bash
sudo systemctl disable --now matibot-v8-xperp-demo.service
sudo journalctl -u matibot-v8-xperp-demo.service -n 200 --no-pager
cd /srv/matibot
git switch --detach bc6b97a
```

Stopping the unit does not flatten an open position. Use the explicit operator
flat command first when venue access and reconciliation are healthy.
