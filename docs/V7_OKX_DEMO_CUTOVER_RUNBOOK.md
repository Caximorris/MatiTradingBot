# V6 to V7 OKX Demo cutover

V6 and V7 cannot own the OKX Demo account simultaneously. This is a controlled
paper-only transition: statistical robustness remains **FRAGILE**, live readiness
remains **NOT_READY**, and no step authorizes live trading or promotion.

Never use `git reset`, `git clean`, force push, or any command that discards VM
changes. Do not put credentials in arguments, JSON, journals, service units, or
terminal output. Values in angle brackets come only from the preceding command
output and must be reviewed before use.

## Validated Linux CLI sequence

`STATISTICAL_ROBUSTNESS = FRAGILE`; `LIVE_READINESS = NOT_READY`. This is paper-only.
Stopping or deactivating never liquidates BTC automatically. V7 inherits the actual OKX Demo
cash/BTC balance, and V7 performance starts from the activation baseline.

### READ-ONLY

```bash
git status --short
git branch --show-current
systemctl is-active matibot-v6-paper.service
systemctl is-active matibot-v7-certified-okx-demo.service
git pull --ff-only origin main
python tools/v6_runtime_observation.py collect-v6-runtime --linux-runtime --service-name matibot-v6-paper.service --repository-path /srv/matibot --config-path /srv/matibot/data/runtime/v6/config.json --state-path /srv/matibot/data/runtime/v6/state.json --journal-path /srv/matibot/data/runtime/v6/journal.jsonl --source-commit "$(git rev-parse HEAD)" --output /srv/matibot/v6-runtime.json --json
python tools/v6_runtime_observation.py observe-okx-demo-account --okx-demo-runtime --runtime-config /srv/matibot/data/runtime/v6/okx-demo-runtime.json --output /srv/matibot/account-observation.json --json
python tools/v6_runtime_observation.py build-v6-audit-inputs --runtime-observation /srv/matibot/v6-runtime.json --account-observation /srv/matibot/account-observation.json --output /srv/matibot/v6-runtime-observation --json
python tools/v6_v7_demo_cutover.py audit-v6 --lease /srv/matibot/data/runtime/v7_certified/account_ownership.jsonl --v6-config /srv/matibot/v6-runtime-observation/v6-config.json --v6-state /srv/matibot/v6-runtime-observation/v6-state.json --v6-journal /srv/matibot/data/runtime/v6/journal.jsonl --account /srv/matibot/v6-runtime-observation/account-observation.json --account-fingerprint "<account-observation.json:fingerprint>"
```

Record `<AUDIT_HASH>` from `audit-v6` field `audit_hash`. Review `verdict=PASS` before continuing.

### STATE-CHANGING

```bash
python tools/v6_v7_demo_cutover.py export-v6-evidence --lease /srv/matibot/data/runtime/v7_certified/account_ownership.jsonl --audit /srv/matibot/v6-audit.json --v6-journal /srv/matibot/data/runtime/v6/journal.jsonl --output /srv/matibot/v6-evidence
python tools/v6_v7_demo_cutover.py stop-v6 --lease /srv/matibot/data/runtime/v7_certified/account_ownership.jsonl --audit /srv/matibot/v6-audit.json --audit-hash "<v6-audit.json:audit_hash>" --evidence /srv/matibot/v6-evidence/v6_demo_evidence.json --instance-id "<v6-runtime-observation/manifest.json:instance_id>" --account-fingerprint "<account-observation.json:fingerprint>" --output /srv/matibot/v6-stop.json
```

**V6 stops at the preceding command.** Verify `systemctl is-active matibot-v6-paper.service`, empty account `open_orders`, and released lease.

Render/install V7 inactive with `render` then `install-inactive`; run `preflight-v7`, then `activate-v7` (**V7 activates here**) for 30 days. Use `status` to inspect reports, orders, fills, parity, and circuit breaker; use `pause-v7`, `resume-v7`, and `deactivate-v7` for lifecycle control. Export the final evidence package only after the reviewed window.

## 1. Inspect before pull (read-only)

```bash
git status --short
git branch --show-current
systemctl is-active matibot-v6-paper.service
systemctl is-active matibot-v7-certified-okx-demo.service
python tools/v6_v7_demo_cutover.py status --lease data/runtime/v7_certified/account_ownership.jsonl
```

## 2. Fetch and fast-forward main (state-changing: checkout only)

```bash
git fetch origin
git rev-parse origin/main
git pull --ff-only origin main
git rev-parse HEAD
python -m pip install -e '.[dev]'
```

Verify the final `HEAD` equals the reviewed deployment SHA:

```bash
test "$(git rev-parse HEAD)" = "<EXPECTED_DEPLOYED_SHA>"
```

## 3. Audit V6 (read-only)

The V6 state, configuration, journal, and account-observation files are prepared
by the reviewed VM adapter. The account file contains only balances, positions,
orders, endpoint confirmation, and the non-secret fingerprint.

```bash
python tools/v6_v7_demo_cutover.py audit-v6 \
  --lease data/runtime/v7_certified/account_ownership.jsonl \
  --v6-config <V6_CONFIG_JSON> --v6-state <V6_STATE_JSON> \
  --v6-journal <V6_JOURNAL_JSONL> --account <ACCOUNT_OBSERVATION_JSON> \
  --account-fingerprint <ACCOUNT_FINGERPRINT> > v6-audit.json
python -m json.tool v6-audit.json
python tools/v6_v7_demo_cutover.py show-audit \
  --lease data/runtime/v7_certified/account_ownership.jsonl --audit v6-audit.json
```

Proceed only when `verdict` is `PASS`. Review `audit_hash`, account cash/BTC
reconciliation, positions, open orders, fills, journal row count and identities,
service identity/state, source/configuration identity, lease, and every reason.

## 4. Export V6 evidence (STATE-CHANGING: writes evidence only)

```bash
python tools/v6_v7_demo_cutover.py export-v6-evidence \
  --lease data/runtime/v7_certified/account_ownership.jsonl \
  --audit v6-audit.json --v6-journal <V6_JOURNAL_JSONL> --output v6-evidence
python -m json.tool v6-evidence/v6_demo_evidence.json
```

Record `<AUDIT_HASH>` from `v6-audit.json` and `<EVIDENCE_HASH>` from the exported
package. An audit `FAIL` or `BLOCKED` must stop here.

## 5. Stop V6 (STATE-CHANGING: stops V6 and releases its lease)

Stopping V6 does **not** close its BTC position. V7 later inherits the real OKX
Demo cash and BTC state.

```bash
python tools/v6_v7_demo_cutover.py stop-v6 \
  --lease data/runtime/v7_certified/account_ownership.jsonl \
  --audit v6-audit.json --audit-hash <AUDIT_HASH> \
  --evidence v6-evidence/v6_demo_evidence.json \
  --instance-id <V6_INSTANCE_ID> --account-fingerprint <ACCOUNT_FINGERPRINT> \
  --output v6-stop.json
python -m json.tool v6-stop.json
```

Verify the stop before continuing (read-only):

```bash
systemctl is-active matibot-v6-paper.service
python tools/v6_v7_demo_cutover.py status --lease data/runtime/v7_certified/account_ownership.jsonl
```

`matibot-v6-paper.service` must be inactive, observed pending orders must be empty,
and the lease must have no active owner. Record `<CUTOVER_HASH>` from `v6-stop.json`.

## 6. Create and install V7 inactive (STATE-CHANGING: files/unit only)

```bash
python tools/v6_v7_demo_cutover.py create-v7-inactive \
  --lease data/runtime/v7_certified/account_ownership.jsonl \
  --audit v6-audit.json --evidence v6-evidence/v6_demo_evidence.json \
  --stop-record v6-stop.json --output v7-inactive.json
sudo install -m 0644 deploy/matibot-v7-certified-okx-demo.service \
  /etc/systemd/system/matibot-v7-certified-okx-demo.service
sudo systemctl daemon-reload
sudo systemctl disable matibot-v7-certified-okx-demo.service
systemctl is-enabled matibot-v7-certified-okx-demo.service || test $? -eq 1
systemctl is-active matibot-v7-certified-okx-demo.service || test $? -eq 3
```

Do not enable or start this unit during installation. It is separate from V6,
`v7_shadow`, generic paper fleets, and live services. Record `<INACTIVE_HASH>`.

## 7. Preflight and activate V7 (activation is STATE-CHANGING)

```bash
python tools/v6_v7_demo_cutover.py preflight-v7 \
  --lease data/runtime/v7_certified/account_ownership.jsonl \
  --account <ACCOUNT_OBSERVATION_JSON> --account-fingerprint <ACCOUNT_FINGERPRINT> \
  --inactive v7-inactive.json > v7-preflight.json
python -m json.tool v7-preflight.json
python tools/v6_v7_demo_cutover.py activate-v7 \
  --lease data/runtime/v7_certified/account_ownership.jsonl \
  --audit v6-audit.json --evidence v6-evidence/v6_demo_evidence.json \
  --stop-record v6-stop.json --inactive v7-inactive.json --preflight v7-preflight.json \
  --ack-fragile --ack-not-live-ready --ack-sole-owner --output v7-activation.json
```

Activation requires the reviewed audit/export/stop/lease/preflight hash chain.
V7 performance begins from `activation_baseline`; prior account performance belongs
to V6. Activation may produce no immediate order when inherited exposure already
matches the V7 target.

## 8. Verify activation and the 30-day run (read-only)

```bash
python tools/v6_v7_demo_cutover.py status \
  --lease data/runtime/v7_certified/account_ownership.jsonl --activation v7-activation.json
systemctl status --no-pager matibot-v7-certified-okx-demo.service
python -m json.tool v7-activation.json
```

Review service/process identity, exclusive lease, inherited cash/BTC baseline,
phase, regime, target, orders, fills, daily report, replay parity, and circuit
breaker. During the 30-day window repeat the status command and review the
candidate-owned journal, evidence, and report directories; a lock, pending order,
duplicate process, missing report, or reconciliation mismatch requires a pause.

## 9. Pause, resume, and deactivate

Pause is STATE-CHANGING and prevents new V7 intents:

```bash
python tools/v6_v7_demo_cutover.py pause-v7 \
  --lease data/runtime/v7_certified/account_ownership.jsonl \
  --activation v7-activation.json --activation-hash <ACTIVATION_HASH> --output v7-pause.json
```

Resume only after reviewed health evidence (STATE-CHANGING):

```bash
python tools/v6_v7_demo_cutover.py resume-v7 \
  --lease data/runtime/v7_certified/account_ownership.jsonl \
  --activation v7-activation.json --activation-hash <ACTIVATION_HASH> \
  --transition v7-pause.json --transition-hash <PAUSE_TRANSITION_HASH> --output v7-resume.json
```

Deactivation is STATE-CHANGING, releases only the V7 lease, preserves balances and
evidence, and never liquidates automatically:

```bash
python tools/v6_v7_demo_cutover.py deactivate-v7 \
  --lease data/runtime/v7_certified/account_ownership.jsonl \
  --activation v7-activation.json --activation-hash <ACTIVATION_HASH> \
  --transition v7-resume.json --transition-hash <RESUME_TRANSITION_HASH> --output v7-deactivate.json
```

## 10. Final evidence export (STATE-CHANGING: copies candidate-owned evidence only)

After the 30-day run, create one immutable package from candidate-owned evidence
(STATE-CHANGING: writes the package; it never deletes or rewrites source state):

```bash
tar -czf v7-final-evidence-<ACTIVATION_HASH>.tgz \
  v6-audit.json v6-evidence/v6_demo_evidence.json v6-stop.json v7-inactive.json \
  v7-preflight.json v7-activation.json v7-pause.json v7-resume.json v7-deactivate.json \
  data/runtime/v7_certified/v7_certified_paper/journal.jsonl \
  data/runtime/v7_certified/v7_certified_paper/evidence \
  data/runtime/v7_certified/v7_certified_paper/reports
```

Store that package through the reviewed evidence-curation procedure. Never delete
the candidate runtime state to make a new package.
