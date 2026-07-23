#!/usr/bin/env bash
# Install the v7 shadow + gated local-paper units without changing the v6 fleet.
set -euo pipefail
APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
RUN_USER="$(whoami)"
cd "$APP_DIR"

.venv/bin/python -c 'from config.settings import load_settings; assert load_settings().is_paper, "TRADING_MODE must be paper"'
git diff --quiet
.venv/bin/python tools/v7_deployment_snapshot.py before
.venv/bin/python tools/v7_paper_setup.py --activate-shadow

for unit in matibot-v7-shadow matibot-v7-paper matibot-v7-promotion; do
  sed -e "s|__APP_DIR__|$APP_DIR|g" -e "s|__RUN_USER__|$RUN_USER|g" "deploy/${unit}.service" \
    | sudo tee "/etc/systemd/system/${unit}.service" > /dev/null
done
sudo systemctl daemon-reload
sudo systemctl enable --now matibot-v7-shadow matibot-v7-promotion matibot-v7-paper
.venv/bin/python tools/v7_deployment_snapshot.py after
.venv/bin/python tools/v7_operational_validation.py
